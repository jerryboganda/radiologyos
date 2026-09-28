"""Queries behind the owner's red review list (ADR 0038, ADR 0041).

Every item comes with what the owner needs to judge it without hunting: the
file name, the exact page or page range, and the evidence itself - the page's
own text beside what the model read, the figure's reading and the source quote,
or the note section's text with every extracted statement highlighted. Only
the caller's own sources (``uploaded_by``) under tenant RLS.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXCERPT = 2000
SECTION = 4000
KIND = {"page_parse": "page", "image_case": "figure", "knowledge_extract": "notes"}
AGENTS = {v: k for k, v in KIND.items()}
STATUSES = {"open": ("review",), "reviewed": ("reviewed",)}
UNIT_HASH = "'chunk:' || left(encode(sha256(convert_to(c.text, 'UTF8')), 'hex'), 32)"

_ITEMS = """
    SELECT e.id, e.source_id, s.title AS source_title,
           coalesce(s.original_filename, s.title) AS file_name, e.agent, e.unit, e.reason,
           e.status, e.owner_verdict, e.owner_note, e.created_at, e.resolved_at
    FROM model_escalations e JOIN sources s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
    WHERE e.status = ANY(:st) AND s.uploaded_by = :u AND s.deleted_at IS NULL
      AND (CAST(:src AS uuid) IS NULL OR e.source_id = CAST(:src AS uuid))
      AND (CAST(:agent AS text) IS NULL OR e.agent = CAST(:agent AS text))
    ORDER BY s.title, e.agent, e.unit LIMIT :n
"""
_FACTS = """
    SELECT c.id, c.statement, c.doubt, c.evidence_span, c.source_id, s.title AS source_title,
           coalesce(s.original_filename, s.title) AS file_name, c.page_from, c.page_to,
           c.status, c.owner_note, c.owner_decided_at,
           ch.heading AS section_heading, left(ch.text, :sec) AS section_text
    FROM claims c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
    LEFT JOIN chunks ch ON ch.id = c.chunk_id
    WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
      AND (CAST(:src AS uuid) IS NULL OR c.source_id = CAST(:src AS uuid))
      AND (CASE WHEN CAST(:open AS boolean) THEN c.status = 'flagged'
                ELSE c.owner_decided_at IS NOT NULL AND c.doubt IS NOT NULL END)
    ORDER BY s.title, c.page_from, c.id LIMIT :n
"""
_PAGES = """
    SELECT p.source_id, p.page_no, left(p.native_text, :ex) AS own_text, p.vision_status,
           (SELECT left(string_agg(c.text, E'\n\n' ORDER BY c.chunk_no), :ex) FROM chunks c
            WHERE c.source_id = p.source_id AND p.page_no BETWEEN c.page_from AND c.page_to)
           AS reading
    FROM source_pages p
    JOIN unnest(CAST(:sids AS uuid[]), CAST(:pages AS int[])) AS x(s, n)
      ON p.source_id = x.s AND p.page_no = x.n
"""
_FIGURES = """
    SELECT f.id, f.source_id, f.page_no, f.figure_no, f.caption, f.description, f.modality,
           f.anatomy, f.findings, f.source_quote, f.impression_origin,
           f.image_key IS NOT NULL AS has_image
    FROM figures f
    JOIN unnest(CAST(:sids AS uuid[]), CAST(:pages AS int[])) AS x(s, n)
      ON f.source_id = x.s AND f.page_no = x.n
    ORDER BY f.page_no, f.figure_no
"""
_CHUNKS = f"""
    SELECT c.id, c.source_id, c.heading, left(c.text, :sec) AS text, c.page_from, c.page_to,
           {UNIT_HASH} AS unit
    FROM chunks c WHERE c.source_id = ANY(:sids) AND {UNIT_HASH} = ANY(:units)
"""  # nosec B608 - constant SQL
_CLAIMS = """
    SELECT chunk_id, statement, evidence_span, status FROM claims
    WHERE chunk_id = ANY(:cids) AND status <> 'rejected' ORDER BY chunk_id, page_from
"""
_SUMMARY_ITEMS = """
    SELECT e.source_id, s.title, coalesce(s.original_filename, s.title) AS file_name,
           e.agent, e.reason, e.status, count(*) AS n
    FROM model_escalations e JOIN sources s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
    WHERE e.status IN ('review', 'reviewed') AND s.uploaded_by = :u AND s.deleted_at IS NULL
    GROUP BY 1, 2, 3, 4, 5, 6
"""
_SUMMARY_FACTS = """
    SELECT c.source_id, s.title, coalesce(s.original_filename, s.title) AS file_name,
           c.status = 'flagged' AS open, count(*) AS n
    FROM claims c JOIN sources s ON s.id = c.source_id AND s.tenant_id = c.tenant_id
    WHERE s.uploaded_by = :u AND s.deleted_at IS NULL
      AND (c.status = 'flagged' OR (c.owner_decided_at IS NOT NULL AND c.doubt IS NOT NULL))
    GROUP BY 1, 2, 3, 4
"""


def page_of(unit: str) -> int | None:
    return int(unit[5:]) if unit.startswith("page:") and unit[5:].isdigit() else None


async def items(
    session: AsyncSession, user_id: UUID, status: str, source_id: UUID | None,
    kind: str | None, limit: int,
) -> list[dict[str, Any]]:
    params = {"st": list(STATUSES[status]), "u": user_id, "src": source_id,
              "agent": AGENTS.get(kind or ""), "n": limit}
    rows = [dict(r) for r in (await session.execute(text(_ITEMS), params)).mappings()]
    details = await _details(session, rows)
    for row in rows:
        row["kind"] = KIND.get(row["agent"], "notes")
        row.update(details.get(row["id"], {}))
    rows.sort(key=lambda r: (str(r["file_name"]).lower(), r["page_from"] or 0, r["kind"]))
    return rows


async def facts(
    session: AsyncSession, user_id: UUID, status: str, source_id: UUID | None, limit: int,
) -> list[dict[str, Any]]:
    params = {"u": user_id, "src": source_id, "open": status == "open", "n": limit,
              "sec": SECTION}
    return [dict(r) for r in (await session.execute(text(_FACTS), params)).mappings()]


async def summary(session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Per file: open and reviewed counts by kind and reason, newest work first."""
    files: dict[UUID, dict[str, Any]] = {}

    def entry(row: Any) -> dict[str, Any]:
        return files.setdefault(row.source_id, {
            "source_id": row.source_id, "source_title": row.title, "file_name": row.file_name,
            "open_pages": 0, "open_figures": 0, "open_notes": 0, "open_facts": 0,
            "reviewed": 0, "reasons": {}})

    for row in await session.execute(text(_SUMMARY_ITEMS), {"u": user_id}):
        e = entry(row)
        if row.status == "reviewed":
            e["reviewed"] += int(row.n)
            continue
        e[f"open_{KIND.get(row.agent, 'notes')}s"] += int(row.n)
        e["reasons"][row.reason] = e["reasons"].get(row.reason, 0) + int(row.n)
    for row in await session.execute(text(_SUMMARY_FACTS), {"u": user_id}):
        e = entry(row)
        e["open_facts" if row.open else "reviewed"] += int(row.n)
    return sorted(files.values(), key=lambda f: str(f["file_name"]).lower())


async def _details(session: AsyncSession, rows: list[dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
    out: dict[UUID, dict[str, Any]] = {}
    paged = [(r, page_of(r["unit"])) for r in rows if r["agent"] in ("page_parse", "image_case")]
    paged = [(r, p) for r, p in paged if p is not None]
    for row, page in paged:
        out[row["id"]] = {"page_from": page, "page_to": page}
    if paged:
        await _page_details(session, paged, out)
    notes = [r for r in rows if r["unit"].startswith("chunk:")]
    if notes:
        await _note_details(session, notes, out)
    return out


async def _page_details(
    session: AsyncSession, paged: list[tuple[dict[str, Any], int | None]],
    out: dict[UUID, dict[str, Any]],
) -> None:
    params = {"sids": [r["source_id"] for r, _ in paged], "pages": [p for _, p in paged],
              "ex": EXCERPT}
    pages = {(p.source_id, p.page_no): p for p in await session.execute(text(_PAGES), params)}
    figures: dict[tuple[UUID, int], list[dict[str, Any]]] = {}
    for f in (await session.execute(text(_FIGURES), params)).mappings():
        figures.setdefault((f["source_id"], f["page_no"]), []).append(_figure(dict(f)))
    for row, page in paged:
        found = pages.get((row["source_id"], page))
        detail = out[row["id"]]
        detail["page_status"] = found.vision_status if found else None
        if row["agent"] == "page_parse":
            detail["own_text"] = found.own_text if found else None
            detail["reading"] = found.reading if found else None
        else:
            detail["figures"] = figures.get((row["source_id"], page or 0), [])


def _figure(f: dict[str, Any]) -> dict[str, Any]:
    findings = f.pop("findings")
    if isinstance(findings, str):
        findings = json.loads(findings)
    f["findings"] = [str(x) for x in findings][:12] if isinstance(findings, list) else (
        [json.dumps(findings)[:600]] if findings else [])
    return f


async def _note_details(
    session: AsyncSession, notes: list[dict[str, Any]], out: dict[UUID, dict[str, Any]]
) -> None:
    params = {"sids": list({r["source_id"] for r in notes}), "units": [r["unit"] for r in notes],
              "sec": SECTION}
    chunks = {(c.source_id, c.unit): c for c in await session.execute(text(_CHUNKS), params)}
    claims: dict[UUID, list[dict[str, Any]]] = {}
    if chunks:
        cids = [c.id for c in chunks.values()]
        for c in (await session.execute(text(_CLAIMS), {"cids": cids})).mappings():
            claims.setdefault(c["chunk_id"], []).append(
                {"statement": c["statement"], "evidence_span": c["evidence_span"],
                 "status": c["status"]})
    for row in notes:
        chunk = chunks.get((row["source_id"], row["unit"]))
        out[row["id"]] = {
            "page_from": chunk.page_from if chunk else None,
            "page_to": chunk.page_to if chunk else None,
            "section_heading": chunk.heading if chunk else None,
            "section_text": chunk.text if chunk else None,
            "statements": claims.get(chunk.id, []) if chunk else [],
        }
