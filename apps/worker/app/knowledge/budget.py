"""Per-run model-call budget for the knowledge-depth pass (ADR 0030)."""

from __future__ import annotations

from apps.worker.app.knowledge.notes import Continue

UNITS_PER_RUN = 20


class Budget:
    """Raises ``Continue`` once a run has spent its model calls, so the task
    re-queues itself and stays under the broker's visibility timeout."""

    def __init__(self, units: int = UNITS_PER_RUN) -> None:
        self.left = units
        self.spent = 0

    def spend(self) -> None:
        if self.left <= 0:
            raise Continue
        self.left -= 1
        self.spent += 1
