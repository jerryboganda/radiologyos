"""Rolling thread memory for the tutor (ADR 0025).

A thread keeps its most recent turns verbatim. When the whole uncovered history
(the stored summary plus every turn after it) exceeds a token budget, the turns
that fall out of the verbatim window are folded into a persisted rolling
summary by ``tutor_memory`` (no tools). The summary is context only: prompts
mark it as not citable, it never replaces a citation, and it is never sent to
the web agent (it may paraphrase excerpt text). If summarising fails, the old
summary and the verbatim window are used and the fold is retried next turn.
Nothing here logs turn or summary text (hard rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from packages.models.gateway import Transport, load_agent, run_agent
from packages.tutor.models import ThreadMemory
from packages.tutor.prompts import Turn, escape

MEMORY_AGENT = "tutor_memory"
VERBATIM_MESSAGES = 6
BUDGET_TOKENS = 3000
TURN_CHARS = 4000


def estimate_tokens(text: str) -> int:
    """A cheap, conservative token estimate (about four characters per token)."""
    return (len(text) + 3) // 4


@dataclass(frozen=True, slots=True)
class MemoryState:
    """What is stored for a thread: the summary and how many messages it covers."""

    summary: str = ""
    covered: int = 0
    uncovered: tuple[Turn, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryPlan:
    verbatim: tuple[Turn, ...]
    fold: tuple[Turn, ...]
    summary: str
    covered: int


@dataclass(frozen=True, slots=True)
class MemoryUpdate:
    """A new summary to persist with the exchange."""

    summary: str
    covered: int
    agent_version: str


def plan_memory(
    state: MemoryState, verbatim: int = VERBATIM_MESSAGES, budget: int = BUDGET_TOKENS
) -> MemoryPlan:
    """Keep everything while it fits the budget; otherwise fold all but the newest turns."""
    turns = state.uncovered
    total = estimate_tokens(state.summary) + sum(estimate_tokens(t.content) for t in turns)
    if total <= budget or len(turns) <= verbatim:
        return MemoryPlan(turns, (), state.summary, state.covered)
    return MemoryPlan(turns[-verbatim:], turns[:-verbatim], state.summary, state.covered)


def memory_prompt(summary: str, fold: Sequence[Turn]) -> str:
    turns = "\n".join(f'<turn role="{t.role}">{escape(t.content[:TURN_CHARS])}</turn>'
                      for t in fold)
    previous = f"<previous_summary>\n{escape(summary)}\n</previous_summary>\n\n" if summary else ""
    return previous + f"<turns>\n{turns}\n</turns>"


def fold_memory(transport: Transport, plan: MemoryPlan) -> MemoryUpdate | None:
    """Summarise ``plan.fold`` into the rolling summary; None if nothing to fold.

    Raises ModelCallError on failure; callers keep the previous summary.
    """
    if not plan.fold:
        return None
    parsed, _ = run_agent(transport, MEMORY_AGENT, memory_prompt(plan.summary, plan.fold))
    summary = " ".join(cast(ThreadMemory, parsed).summary.split())
    return MemoryUpdate(summary=summary, covered=plan.covered + len(plan.fold),
                        agent_version=load_agent(MEMORY_AGENT).key)
