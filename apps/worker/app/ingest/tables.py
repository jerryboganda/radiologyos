"""The ``extract_tables`` step: table blocks become structured rows (ADR 0030).

Runs inside the chunk step's tenant transaction, after the blocks it reads are
final (native pass, then again after the vision pass). It replaces the
source's ``source_tables`` rows from its current ``table`` blocks, so a re-run
or a reprocess is idempotent and costs no model call. Only counts are logged.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.worker.app.ingest.db import as_json
from packages.library.tables import parse_table, plain_text, to_csv, to_html
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def table_blocks(session: AsyncSession, source_id: UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT page_no, block_no, text, bbox FROM source_blocks "
            "WHERE source_id = :s AND kind = 'table' ORDER BY page_no, block_no"
        ),
        {"s": source_id},
    )
    return [dict(row) for row in rows.mappings()]


async def extract_tables(session: AsyncSession, tenant_id: UUID, source_id: UUID) -> int:
    """Rebuild the source's structured tables; returns how many were stored."""
    blocks = await table_blocks(session, source_id)
    await session.execute(text("DELETE FROM source_tables WHERE source_id = :s"),
                          {"s": source_id})
    stored = 0
    for block in blocks:
        table = parse_table(block["text"])
        if table is None:
            continue
        await session.execute(
            text(
                "INSERT INTO source_tables (tenant_id, source_id, page_no, block_no, bbox, "
                "n_rows, n_cols, header, cells, csv, html, plain) VALUES (:t, :s, :p, :b, "
                ":bbox, :nr, :nc, :h, CAST(:cells AS jsonb), :csv, :html, :plain)"
            ),
            {"t": tenant_id, "s": source_id, "p": block["page_no"], "b": block["block_no"],
             "bbox": [float(v) for v in block["bbox"]], "nr": table.n_rows,
             "nc": table.n_cols, "h": table.header, "cells": as_json(table.rows),
             "csv": to_csv(table), "html": to_html(table), "plain": plain_text(table)},
        )
        stored += 1
    return stored
