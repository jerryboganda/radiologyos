"""Synthetic knowledge rows for the vault export gates (M6/M7).

Two users in one tenant plus a user in another tenant, each with sources,
concepts, cited claims, edges, and cards. Row ids are fixed so renders are
comparable across runs. All text is synthetic.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from apps.worker.app.datarights.vault import (
    VaultCard,
    VaultClaim,
    VaultConcept,
    VaultEdge,
    VaultRows,
    VaultSource,
)

USER_A = UUID("10000000-0000-4000-8000-00000000000a")
USER_B = UUID("10000000-0000-4000-8000-00000000000b")
CHEST = UUID("c1000000-0000-4000-8000-0000000000c1")
HEAD = UUID("c2000000-0000-4000-8000-0000000000c2")
GGO = UUID("a1000000-0000-4000-8000-000000000001")
EFFUSION = UUID("a2000000-0000-4000-8000-000000000002")
SAH = UUID("a3000000-0000-4000-8000-000000000003")


def _claim(n: int, concept: UUID, source: UUID, statement: str, page: int,
           **extra: Any) -> VaultClaim:
    return VaultClaim(UUID(f"b{n:07d}-0000-4000-8000-000000000000"), concept, statement,
                      f"Evidence for {statement.lower()}", extra.pop("status", "active"),
                      source, page, extra.pop("page_to", page), ((page, n),))


def rows_for_user_a() -> VaultRows:
    sources = (VaultSource(CHEST, "Synthetic chest notes"),)
    concepts = (VaultConcept(GGO, "Ground-glass opacity", "finding", ("GGO",), "CHEST"),
                VaultConcept(EFFUSION, "Pleural effusion", "finding", (), "CHEST"))
    claims = (
        _claim(1, GGO, CHEST, "Ground-glass opacity suggests alveolar filling.", 1),
        _claim(2, EFFUSION, CHEST, "An effusion blunts the costophrenic angle.", 2,
               page_to=3),
        _claim(3, EFFUSION, CHEST, "Effusions layer on decubitus views.", 2,
               status="disputed"),
    )
    edges = (VaultEdge(GGO, EFFUSION, "associated_with"),)
    cards = (VaultCard(UUID("80000000-0000-4000-8000-000000000001"), "CHEST", "Pleura",
                       "What blunts the costophrenic angle?", "A pleural effusion.",
                       CHEST, 2, 2),)
    return VaultRows(sources, concepts, claims, edges, cards)


def rows_for_user_b() -> VaultRows:
    """Another member's (or another tenant's) knowledge: never in A's vault."""
    sources = (VaultSource(HEAD, "Synthetic head CT notes"),)
    concepts = (VaultConcept(SAH, "Subarachnoid haemorrhage", "diagnosis", (), "NEURO"),)
    claims = (_claim(9, SAH, HEAD, "Subarachnoid blood is hyperdense on CT.", 4),)
    return VaultRows(sources, concepts, claims, (), ())


def without_source(rows: VaultRows, source_id: UUID) -> VaultRows:
    """What the loader returns once a source is deleted (its rows cascade)."""
    return replace(
        rows,
        sources=tuple(s for s in rows.sources if s.id != source_id),
        claims=tuple(c for c in rows.claims if c.source_id != source_id),
    )
