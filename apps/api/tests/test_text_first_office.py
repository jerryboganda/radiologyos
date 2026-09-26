"""pdf-inspector text-first routing covers PPTX/DOCX through their LibreOffice PDF."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from apps.worker.app.ingest import steps
from packages.library.render import RenderError


class _Store:
    def get(self, _key: str) -> bytes:
        return b"PK-office-bytes"


class _Content:
    marked: list[int] = []

    @staticmethod
    async def set_vision_status(_s: Any, _src: Any, page_no: int, *_a: Any) -> None:
        _Content.marked.append(page_no)


class _Db:
    @staticmethod
    @asynccontextmanager
    async def tenant_tx(*_a: Any) -> Any:
        yield None


def _deps() -> Any:
    return steps.Deps(engine=None, store=_Store(), transport=None, embedder=None)  # type: ignore[arg-type]


PAGES = [{"page_no": 1, "native_text": "x" * 900}, {"page_no": 2, "native_text": "y" * 900}]
JOB = {"tenant_id": uuid4(), "entity_id": uuid4()}


@pytest.mark.parametrize("kind", ["pptx", "docx"])
async def test_office_pages_with_good_text_skip_every_model(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def convert(data: bytes, ext: str) -> bytes:
        seen["convert"] = (data, ext)
        return b"%PDF-converted"

    def inspect(data: bytes, chars: Any) -> set[int]:
        seen["inspected"] = data
        return {1}

    monkeypatch.setattr(steps, "office_to_pdf", convert)
    monkeypatch.setattr(steps, "text_only_pages", inspect)
    monkeypatch.setattr(steps, "db", _Db)
    monkeypatch.setattr(steps, "db_content", _Content)
    _Content.marked = []
    todo = await steps._keep_text_pages(_deps(), JOB, {"kind": kind, "storage_key": "k"}, PAGES)
    assert seen["convert"] == (b"PK-office-bytes", kind)
    assert seen["inspected"] == b"%PDF-converted"  # pdf-inspector reads the converted PDF
    assert [p["page_no"] for p in todo] == [2] and _Content.marked == [1]


async def test_a_failed_conversion_sends_every_page_to_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_a: Any) -> bytes:
        raise RenderError("no")

    monkeypatch.setattr(steps, "office_to_pdf", fail)
    todo = await steps._keep_text_pages(_deps(), JOB, {"kind": "pptx", "storage_key": "k"}, PAGES)
    assert todo == PAGES
