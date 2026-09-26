"""The vault loader's scoping and its place in the account export ZIP (ADR 0031)."""

from __future__ import annotations

import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.worker.app.datarights import export, notes, vault_sql
from apps.worker.app.datarights.vault import escape, pages, slug, unescape
from evals.checks._vault_support import CHEST, GGO, USER_A, rows_for_user_a

TENANT = UUID("20000000-0000-4000-8000-0000000000aa")


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    """Answers each vault statement with scripted rows and records the binds."""

    def __init__(self, answers: dict[Any, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.calls.append((str(statement), params))
        return _Result(self.answers.get(statement, []))


def _answers() -> dict[Any, list[dict[str, Any]]]:
    claim_id = uuid4()
    return {
        vault_sql.SOURCES_SQL: [{"id": CHEST, "title": "Synthetic chest notes"}],
        vault_sql.CONCEPTS_SQL: [{"id": GGO, "name": "Ground-glass opacity",
                                  "concept_type": None, "aliases": None,
                                  "curriculum_code": "CHEST"}],
        vault_sql.CLAIMS_SQL: [{"id": claim_id, "concept_id": GGO, "statement": "S.",
                                "evidence_span": "E.", "status": "active",
                                "source_id": CHEST, "page_from": 2, "page_to": 3,
                                "blocks": '[{"page_no": 2, "block_no": 4}, {"page_no": "x"}]'}],
        vault_sql.CARDS_SQL: [{"id": uuid4(), "curriculum_code": "CHEST", "topic": None,
                               "front": "Q?", "back": "A.", "source_id": None,
                               "page_from": "2", "page_to": "bad"}],
    }


async def test_loader_binds_only_the_user_and_filters_live_own_sources() -> None:
    session = _Session(_answers())
    rows = await vault_sql.load_vault(session, USER_A)  # type: ignore[arg-type]
    assert [params for _, params in session.calls] == [{"u": USER_A}] * 5
    for sql, _ in session.calls:
        assert "uploaded_by = :u" in sql or "user_id = :u" in sql
        if "sources" in sql:
            assert "deleted_at IS NULL" in sql
    assert rows.claims[0].blocks == ((2, 4),)
    assert rows.concepts[0].concept_type == "other" and rows.concepts[0].aliases == ()
    assert rows.cards[0].page_from == 2 and rows.cards[0].page_to is None


async def test_export_zip_carries_the_vault_and_counts_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    @asynccontextmanager
    async def fake_tx(engine: Any, tenant_id: UUID) -> AsyncIterator[object]:
        assert tenant_id == TENANT
        yield object()

    async def no_rows(*_: Any) -> int:
        return 0

    async def text_of(*_: Any) -> str:
        return "# notes\n"

    async def vault_rows(_session: Any, user_id: UUID) -> Any:
        assert user_id == USER_A
        return rows_for_user_a()

    async def no_files(*_: Any) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(export, "tenant_tx", fake_tx)
    monkeypatch.setattr(export, "_write_table", no_rows)
    monkeypatch.setattr(notes, "cards_markdown", text_of)
    monkeypatch.setattr(notes, "claims_markdown", text_of)
    monkeypatch.setattr(export, "load_vault", vault_rows)
    monkeypatch.setattr(export, "_object_files", no_files)
    deps: Any = type("Deps", (), {"engine": None, "store": None})()
    path = tmp_path / "export.zip"
    counts = await export.write_zip(deps, TENANT, USER_A, uuid4(), path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        readme = archive.read("README.md").decode()
    vault_names = [n for n in names if n.startswith("vault/")]
    assert "vault/index.md" in vault_names
    assert counts["vault_files"] == len(vault_names) > 1
    assert "`vault/`" in readme


def test_escape_round_trips_and_neutralises_markup() -> None:
    raw = "a [[b]] <c> ^d %e% `f` #g |h| *i* _j_ \\k"
    escaped = escape(raw)
    assert "[[" not in escaped and "<c>" not in escaped
    assert unescape(escaped) == raw
    assert escape("line one\n\n  line two") == "line one line two"


def test_slug_is_ascii_bounded_and_id_suffixed() -> None:
    row = UUID("abcdef01-0000-4000-8000-000000000000")
    assert slug("Crazy-paving / PAP (HRCT)", row) == "crazy-paving-pap-hrct-abcdef01"
    assert slug("   ", row) == "untitled-abcdef01"
    assert len(slug("x" * 500, row)) <= 69


@pytest.mark.parametrize(("first", "last", "text"),
                         [(3, 3, "p. 3"), (3, 5, "pp. 3-5"), (None, None, "page unknown"),
                          (4, None, "p. 4")])
def test_page_ranges(first: int | None, last: int | None, text: str) -> None:
    assert pages(first, last) == text
