"""Answer one tutor question: sources first, authoritative web second (ADR 0013).

1. If anything was retrieved, ``tutor_answer`` (no tools) answers only from the
   numbered excerpts (``S1``..) and described figures (``F1``..) and reports
   its coverage. Non-citable context (rolling thread summary, the AI reading of
   an attached image, the page being read) rides along, labelled (ADR 0025).
2. If coverage is not full and the caller allows it, ``tutor_web`` (WebSearch
   and WebFetch only) researches the question on authoritative radiology sites.
   It receives the question, earlier questions, and at most the structured
   findings of an attached image — never excerpt text or the thread summary —
   so uploaded content cannot steer web requests.
3. ``grounding`` verifies every citation and drops anything uncited.
4. ``judge`` (``grounding_judge``, no tools) checks that each segment is
   actually supported by the text it cites; unsupported segments are dropped.

Runs synchronously (the transport blocks for minutes); API callers run it in a
threadpool and may pass ``on_status`` to report progress (``answering``,
``web_research``, ``judging``) and ``on_draft`` to receive draft text while the
answer and web steps are written (ADR 0025). Drafts are unverified and are
always superseded by the returned, judged answer. Nothing here logs question,
excerpt, or answer text (hard rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from packages.models.claude_code import ModelCallError
from packages.models.gateway import Transport, load_agent, run_agent
from packages.tutor.draft import DraftCallback, DraftTracker
from packages.tutor.grounding import (
    Excerpt,
    FigureExcerpt,
    combine,
    ground_sources,
    ground_web,
    page_summaries,
)
from packages.tutor.judge import JUDGE_AGENT, StatusCallback, judge_segments
from packages.tutor.models import (
    GroundedAnswer,
    LayoutAnswer,
    Segment,
    SourceAnswer,
    WebAnswer,
)
from packages.tutor.prompts import Context, Turn, source_prompt, web_prompt

__all__ = ["Context", "Turn", "answer_question", "source_prompt", "web_prompt"]

SOURCE_AGENT = "tutor_answer"
WEB_AGENT = "tutor_web"
WEB_UNAVAILABLE = "Web research was unavailable, so only your sources were used."


def agent_version(*names: str) -> str:
    return "+".join(load_agent(name).key for name in names)


def _run_drafted(
    transport: Transport, agent: str, prompt: str, phase: str, on_draft: DraftCallback | None
) -> object:
    tracker = DraftTracker(phase, on_draft) if on_draft is not None else None
    parsed, _ = run_agent(transport, agent, prompt, on_delta=tracker)
    if tracker is not None:
        tracker.flush()
    return parsed


@dataclass(frozen=True, slots=True)
class _Ask:
    """One question with everything the agents see."""

    question: str
    excerpts: Sequence[Excerpt]
    figures: Sequence[FigureExcerpt]
    history: Sequence[Turn]
    context: Context


def _ask_sources(
    transport: Transport, ask: _Ask, on_draft: DraftCallback | None
) -> tuple[list[Segment], int, str]:
    prompt = source_prompt(ask.question, ask.excerpts, ask.history, ask.figures, ask.context)
    answer = cast(SourceAnswer | LayoutAnswer,
                  _run_drafted(transport, SOURCE_AGENT, prompt, "sources", on_draft))
    segments, dropped = ground_sources(answer, ask.excerpts, ask.figures)
    return segments, dropped, answer.coverage if segments else "none"


def _ask_web(
    transport: Transport, ask: _Ask, on_draft: DraftCallback | None
) -> tuple[list[Segment], int, dict[str, str]]:
    prompt = web_prompt(ask.question, ask.history, ask.context.image)
    answer = cast(WebAnswer, _run_drafted(transport, WEB_AGENT, prompt, "web", on_draft))
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
    transport: Transport, ask: _Ask, allow_web: bool,
    on_status: StatusCallback | None, on_draft: DraftCallback | None,
) -> tuple[_Draft, bool]:
    """Steps 1-3: source answer, optional web research, structural citation checks."""
    draft = _Draft(source=[], web=[], dropped=0, summaries={}, used=[])
    coverage = "none"
    if ask.excerpts or ask.figures:
        _report(on_status, "answering")
        draft.used.append(SOURCE_AGENT)
        draft.source, draft.dropped, coverage = _ask_sources(transport, ask, on_draft)
    web_attempted = allow_web and coverage != "full"
    if web_attempted:
        _report(on_status, "web_research")
        draft.used.append(WEB_AGENT)
        try:
            draft.web, web_dropped, draft.summaries = _ask_web(transport, ask, on_draft)
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
    context: Context | None = None,
    on_draft: DraftCallback | None = None,
) -> GroundedAnswer:
    """Return a grounded, judged answer; raises ModelCallError if the answer step fails.

    ``judge=False`` is honoured only because the caller passes an explicit
    deployment setting; skipped segments are labelled "not verified".
    """
    ask = _Ask(question, excerpts, figures, history, context or Context())
    draft, web_attempted = _draft(transport, ask, allow_web, on_status, on_draft)
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
