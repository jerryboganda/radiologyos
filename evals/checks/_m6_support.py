"""Fakes for the M6 gate: a statement-recording session and a fake tenant_tx.

The session answers each statement from a small script keyed on SQL fragments
and records ``(sql, params, tenant)`` so tests can assert what ran, in which
order, and inside which tenant transaction. No database is involved; the row
level proofs are ``test_library_live.py`` and ``test_data_rights_live.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID


class Result:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self) -> Result:
        return Result([r[0] if isinstance(r, tuple) else r for r in self._rows])

    def all(self) -> list[Any]:
        return list(self._rows)

    def mappings(self) -> Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def __iter__(self) -> Any:
        return iter(self._rows)


Script = list[tuple[str, Callable[[dict[str, Any]], Result]]]


class RecordingSession:
    def __init__(self, script: Script | None = None, tenant: UUID | None = None) -> None:
        self.script = script or []
        self.tenant = tenant
        self.calls: list[tuple[str, dict[str, Any], UUID | None]] = []
        self.commits = 0

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Result:
        sql = " ".join(str(statement).split())
        self.calls.append((sql, dict(params or {}), self.tenant))
        for fragment, answer in self.script:
            if fragment in sql:
                return answer(dict(params or {}))
        return Result()

    async def commit(self) -> None:
        self.commits += 1

    def sql(self) -> list[str]:
        return [sql for sql, _, _ in self.calls]


class TenantTx:
    """Stands in for ``tenant_tx``: every transaction shares one recorder."""

    def __init__(self, session: RecordingSession) -> None:
        self.session = session
        self.tenants: list[UUID] = []

    @asynccontextmanager
    async def __call__(self, engine: Any, tenant_id: UUID) -> AsyncIterator[RecordingSession]:
        self.tenants.append(tenant_id)
        previous, self.session.tenant = self.session.tenant, tenant_id
        try:
            yield self.session
        finally:
            self.session.tenant = previous
