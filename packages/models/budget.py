"""Lifetime Voyage token guard (ADR 0019).

The owner's rule: Voyage embedding stops hard at the cap (195M tokens, below
the 200M free allowance) and the admin gets a red alert; an amber warning
fires at the warn level. There is no silent fallback and the cap is only ever
raised by an explicit ``models.yaml`` change with an ADR amendment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from packages.models.routing import FREE_TIER_TOKENS, EmbeddingBudget

Level = Literal["ok", "amber", "red"]
# List prices per million tokens (docs.voyageai.com, September 2026).
LIST_PRICE_PER_M = {"voyage-4-large": 0.12, "voyage-4": 0.06, "voyage-4-lite": 0.02}


class EmbeddingBudgetExhausted(RuntimeError):
    """The next Voyage request would pass the hard cap; nothing was sent."""


@dataclass(frozen=True, slots=True)
class BudgetState:
    used: int
    budget: EmbeddingBudget

    @property
    def level(self) -> Level:
        if self.used >= self.budget.hard_cap_tokens:
            return "red"
        if self.used >= self.budget.warn_tokens:
            return "amber"
        return "ok"

    @property
    def free_tier_remaining(self) -> int:
        return max(FREE_TIER_TOKENS - self.used, 0)

    def check(self, estimated_tokens: int) -> None:
        """Refuse any request that could take usage past the hard cap."""
        if self.used + estimated_tokens > self.budget.hard_cap_tokens:
            raise EmbeddingBudgetExhausted("embedding budget exhausted")


def crossed(before: int, after: int, budget: EmbeddingBudget) -> list[Level]:
    """Alert levels newly reached by moving usage from ``before`` to ``after``."""
    levels: list[Level] = []
    if before < budget.warn_tokens <= after:
        levels.append("amber")
    if before < budget.hard_cap_tokens <= after:
        levels.append("red")
    return levels


def list_price_usd(tokens: int, model: str) -> float:
    return round(tokens / 1_000_000 * LIST_PRICE_PER_M.get(model, 0.12), 4)


def billed_estimate_usd(tokens: int, model: str) -> float:
    """What Voyage would charge beyond the free allowance (normally 0)."""
    return list_price_usd(max(tokens - FREE_TIER_TOKENS, 0), model)
