"""Answer one tutor question: sources first, authoritative web second (ADR 0013).

1. If anything was retrieved, ``tutor_answer`` (no tools) answers only from the
   numbered excerpts (``S1``..) and described figures (``F1``..) and reports
   its coverage.
2. If coverage is not full and the caller allows it, ``tutor_web`` (WebSearch
   and WebFetch only) researches the question on authoritative radiology sites.
   It receives the question and earlier questions only — never excerpt text —
   so uploaded content cannot steer web requests.
3. ``grounding`` verifies every citation and drops anything uncited.
4. ``judge`` (``grounding_judge``, no tools) checks that each segment is
   actually supported by the text it cites; unsupported segments are dropped.

Runs synchronously (the transport blocks for minutes); API callers run it in a
threadpool and may pass ``on_status`` to report progress (``answering``,
``web_research``, ``judging``). Nothing here logs question, excerpt, or answer
text (hard rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from packages.models.claude_code import ModelCallError
from packages.models.gateway import Transport, load_agent, run_agent
from packages.tutor.grounding import (
    Excerpt,
    FigureExcerpt,
    combine,
    ground_sources,
    ground_web,
    page_summaries,
)
from packages.tutor.judge import JUDGE_AGENT, StatusCallback, judge_segments
from packages.tutor.models import GroundedAnswer, Segment, SourceAnswer, WebAnswer

SOURCE_AGENT = "tutor_answer"
WEB_AGENT = "tutor_web"
EXCERPT_CHARS = 4000
HISTORY_CHARS = 1500
WEB_UNAVAILABLE = "Web research was unavailable, so only your sources were used."


@dataclass(frozen=True, slots=True)
class Turn:
    role: str
    content: str


def _escape(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _history_block(history: Sequence[Turn], questions_only: bool) -> str:
    turns = [t for t in history if t.role == "user" or not questions_only]
    if not turns:
        return ""
    lines = [f"{t.role}: {_escape(t.content[:HISTORY_CHARS])}" for t in turns]
    return ("<conversation note=\"earlier turns, for context only; not citable\">\n"
            + "\n".join(lines) + "\n</conversation>\n\n")


def _figure_block(figures: Sequence[FigureExcerpt]) -> str:
    if not figures:
        return ""
    blocks = [
        f'<figure id="{f.label}" source="{_escape(f.source_title)}" page="{f.page_no}" '
        f'modality="{_escape(f.modality)}" anatomy="{_escape(f.anatomy)}" '
        f'caption="{_escape(f.caption)}">\n{_escape(f.description[:EXCERPT_CHARS])}\n</figure>'
        for f in figures
    ]
    return ("<figures note=\"AI-generated descriptions of images in the candidate's "
            "material; citable by id\">\n" + "\n".join(blocks) + "\n</figures>\n\n")


def source_prompt(
    question: str, excerpts: Sequence[Excerpt], history: Sequence[Turn],
    figures: Sequence[FigureExcerpt] = (),
) -> str:
    blocks = []
    for e in excerpts:
        pages = str(e.page_from) if e.page_from == e.page_to else f"{e.page_from}-{e.page_to}"
        blocks.append(
            f'<excerpt id="{e.label}" source="{_escape(e.source_title)}" pages="{pages}" '
            f'heading="{_escape(e.heading)}">\n{_escape(e.text[:EXCERPT_CHARS])}\n</excerpt>'
        )
    return (
        _history_block(history, questions_only=False)
        + "<excerpts>\n" + "\n".join(blocks) + "\n</excerpts>\n\n"
        + _figure_block(figures)
        + f"<question>\n{_escape(question)}\n</question>"
    )


def web_prompt(question: str, history: Sequence[Turn]) -> str:
    return (_history_block(history, questions_only=True)
            + f"<question>\n{_escape(question)}\n</question>")


def agent_version(*names: str) -> str:
    return "+".join(load_agent(name).key for name in names)


def _ask_sources(
    transport: Transport, question: str, excerpts: Sequence[Excerpt],
    figures: Sequence[FigureExcerpt], history: Sequence[Turn],
) -> tuple[list[Segment], int, str]:
    prompt = source_prompt(question, excerpts, history, figures)
    parsed, _ = run_agent(transport, SOURCE_AGENT, prompt)
    answer = cast(SourceAnswer, parsed)
    segments, dropped = ground_sources(answer, excerpts, figures)
    return segments, dropped, answer.coverage if segments else "none"


def _ask_web(
    transport: Transport, question: str, history: Sequence[Turn]
) -> tuple[list[Segment], int, dict[str, str]]:
    parsed, _ = run_agent(transport, WEB_AGENT, web_prompt(question, history))
    answer = cast(WebAnswer, parsed)
    segments, dropped = ground_web(answer)
    return segments, dropped, page_summaries(answer)


def _report(on_status: StatusCallback | None, stage: str) -> None:
    if on_status is not None:
        on_status(stage)


@dataclass(slots=True)
class _Draft:
    source: list[Segment]
    web: list[Segment]
    dropped: int
    summaries: dict[str, str]
    used: list[str]
    notice: str | None = None


def _draft(
    transport: Transport, question: str, excerpts: Sequence[Excerpt],
    figures: Sequence[FigureExcerpt], history: Sequence[Turn], allow_web: bool,
    on_status: StatusCallback | None,
) -> tuple[_Draft, bool]:
    """Steps 1-3: source answer, optional web research, structural citation checks."""
    draft = _Draft(source=[], web=[], dropped=0, summaries={}, used=[])
    coverage = "none"
    if excerpts or figures:
        _report(on_status, "answering")
        draft.used.append(SOURCE_AGENT)
        draft.source, draft.dropped, coverage = _ask_sources(
            transport, question, excerpts, figures, history)
    web_attempted = allow_web and coverage != "full"
    if web_attempted:
        _report(on_status, "web_research")
        draft.used.append(WEB_AGENT)
        try:
            draft.web, web_dropped, draft.summaries = _ask_web(transport, question, history)
            draft.dropped += web_dropped
        except ModelCallError:  # includes UsageLimitError; keep a source answer if any
            if not draft.source:
                raise
            draft.notice = WEB_UNAVAILABLE
    return draft, web_attempted


def answer_question(
    transport: Transport,
    question: str,
    excerpts: Sequence[Excerpt],
    history: Sequence[Turn] = (),
    allow_web: bool = True,
    *,
    figures: Sequence[FigureExcerpt] = (),
    judge: bool = True,
    on_status: StatusCallback | None = None,
) -> GroundedAnswer:
    """Return a grounded, judged answer; raises ModelCallError if the answer step fails.

    ``judge=False`` is honoured only because the caller passes an explicit
    deployment setting; skipped segments are labelled "not verified".
    """
    draft, web_attempted = _draft(transport, question, excerpts, figures, history,
                                  allow_web, on_status)
    segments, stats = judge_segments(
        transport, [*draft.source, *draft.web], [*excerpts, *figures], draft.summaries,
        enabled=judge, on_status=on_status,
    )
    if stats.agent_version:
        draft.used.append(JUDGE_AGENT)
    source = [s for s in segments if s.origin == "sources"]
    web = [s for s in segments if s.origin == "web"]
    return combine(source, web, draft.dropped + stats.unsupported, web_attempted=web_attempted,
                   notice=draft.notice, judge=stats,
                   agent_version=agent_version(*draft.used) if draft.used else "")
