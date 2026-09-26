"""Answer one tutor question: sources first, authoritative web second (ADR 0013).

1. If anything was retrieved, ``tutor_answer`` (no tools) answers only from the
   numbered excerpts and reports its coverage.
2. If coverage is not full and the caller allows it, ``tutor_web`` (WebSearch
   and WebFetch only) researches the question on authoritative radiology sites.
   It receives the question and earlier questions only — never excerpt text —
   so uploaded content cannot steer web requests.
3. ``grounding`` verifies every citation and drops anything uncited.

Runs synchronously (the transport blocks for minutes); API callers run it in a
threadpool. Nothing here logs question, excerpt, or answer text (hard rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from packages.models.claude_code import ModelCallError
from packages.models.gateway import Transport, load_agent, run_agent
from packages.tutor.grounding import Excerpt, combine, ground_sources, ground_web
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


def source_prompt(question: str, excerpts: Sequence[Excerpt], history: Sequence[Turn]) -> str:
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
        + f"<question>\n{_escape(question)}\n</question>"
    )


def web_prompt(question: str, history: Sequence[Turn]) -> str:
    return (_history_block(history, questions_only=True)
            + f"<question>\n{_escape(question)}\n</question>")


def agent_version(*names: str) -> str:
    return "+".join(load_agent(name).key for name in names)


def _ask_sources(
    transport: Transport, question: str, excerpts: Sequence[Excerpt], history: Sequence[Turn]
) -> tuple[list[Segment], int, str]:
    parsed, _ = run_agent(transport, SOURCE_AGENT, source_prompt(question, excerpts, history))
    answer = cast(SourceAnswer, parsed)
    segments, dropped = ground_sources(answer, excerpts)
    return segments, dropped, answer.coverage if segments else "none"


def _ask_web(
    transport: Transport, question: str, history: Sequence[Turn]
) -> tuple[list[Segment], int]:
    parsed, _ = run_agent(transport, WEB_AGENT, web_prompt(question, history))
    return ground_web(cast(WebAnswer, parsed))


def answer_question(
    transport: Transport,
    question: str,
    excerpts: Sequence[Excerpt],
    history: Sequence[Turn] = (),
    allow_web: bool = True,
) -> GroundedAnswer:
    """Return a grounded answer; raises ModelCallError if the source step fails."""
    used: list[str] = []
    source_segments: list[Segment] = []
    dropped = 0
    coverage = "none"
    if excerpts:
        used.append(SOURCE_AGENT)
        source_segments, dropped, coverage = _ask_sources(transport, question, excerpts, history)
    web_segments: list[Segment] = []
    notice = None
    web_attempted = allow_web and coverage != "full"
    if web_attempted:
        used.append(WEB_AGENT)
        try:
            web_segments, web_dropped = _ask_web(transport, question, history)
            dropped += web_dropped
        except ModelCallError:  # includes UsageLimitError; keep a source answer if any
            if not source_segments:
                raise
            notice = WEB_UNAVAILABLE
    return combine(source_segments, web_segments, dropped, web_attempted=web_attempted,
                   notice=notice, agent_version=agent_version(*used) if used else "")
