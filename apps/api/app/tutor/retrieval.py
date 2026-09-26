"""Tutor retrieval by intent: search, rerank, graph expansion (ADR 0025, ADR 0028).

``search_phase`` (database) runs the hybrid (RRF) search over a candidate
pool, plus one keyword search per subject of a comparison, figures (more for
"show me"), and the Reader page when focused. ``rank_phase`` (no database
transaction) reranks the pool with the metered Voyage reranker and fails
open to RRF order; a comparison keeps at least one hit per subject. The
Reader page's chunks always come first. ``graph_phase`` (database) adds the
K-labelled claims of the top chunks' concepts and their 1-hop neighbours.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from apps.api.app.library import rerank, search
from apps.api.app.tutor import graph
from apps.api.app.tutor.contracts import AskRequest
from packages.tutor.grounding import MAX_FIGURES, Excerpt
from packages.tutor.intent import Route
from sqlalchemy.ext.asyncio import AsyncSession

RETRIEVE = 8
FIGURE_CANDIDATES = 12
SHOW_ME_FIGURES = 6
FOCUS_CHUNKS = 4
FOCUS_FIGURES = 4
SUBJECT_HITS = 6
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")


def lexical_query(question: str) -> str:
    """OR the question's terms so a natural-language question still matches.

    ``websearch_to_tsquery`` ANDs plain words; a full question rarely matches
    one chunk on every word. Stop words are dropped by the text search config.
    """
    terms = list(dict.fromkeys(t.lower() for t in TOKEN.findall(question)))[:40]
    return " or ".join(terms) if terms else question


def figure_limit(route: Route) -> int:
    return SHOW_ME_FIGURES if route.intent == "show_me" else MAX_FIGURES


@dataclass(slots=True)
class Found:
    hits: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    subjects: list[list[dict[str, Any]]] = field(default_factory=list)
    focus_hits: list[dict[str, Any]] = field(default_factory=list)
    reranked: bool = False


def _boost(first: Sequence[dict[str, Any]], rest: Sequence[dict[str, Any]],
           limit: int) -> list[dict[str, Any]]:
    merged: dict[Any, dict[str, Any]] = {}
    for row in [*first, *rest]:
        merged.setdefault(row["id"], row)
    return list(merged.values())[:limit]


async def search_phase(
    session: AsyncSession, user: UUID, body: AskRequest, route: Route, text_query: str,
    vector: Sequence[float] | None,
) -> Found:
    query = lexical_query(text_query)
    hits = await search.hybrid_search(session, user, query, vector,
                                      rerank.candidate_pool(RETRIEVE))
    subjects = [await search.hybrid_search(session, user, lexical_query(s), None, SUBJECT_HITS)
                for s in route.subjects] if route.intent == "compare" else []
    figures = await search.search_figures(session, user, query, FIGURE_CANDIDATES,
                                          query_vector=vector)
    found = Found(hits, figures, subjects)
    if body.focus is not None:
        focus = body.focus
        found.focus_hits = await search.page_chunks(session, user, focus.source_id,
                                                    focus.page_no, FOCUS_CHUNKS)
        found.figures = _boost(await search.page_figures(session, user, focus.source_id,
                                                         focus.page_no, FOCUS_FIGURES),
                               figures, FIGURE_CANDIDATES)
    return found


def cover_subjects(ranked: list[dict[str, Any]], subjects: Sequence[Sequence[dict[str, Any]]],
                   limit: int) -> list[dict[str, Any]]:
    """Keep at least one hit per compared subject, replacing the weakest tail hits."""
    out = list(ranked[:limit])
    for rows in subjects:
        ids = {r["id"] for r in rows}
        if not rows or any(h["id"] in ids for h in out):
            continue
        best = next((h for h in ranked if h["id"] in ids), rows[0])
        if len(out) >= limit:
            out.pop()
        out.append(best)
    return out


async def rank_phase(tenant_id: UUID, text_query: str, found: Found) -> Found:
    """Rerank (fail-open), keep compared subjects, put the Reader page first."""
    pool = _boost(found.hits, [r for rows in found.subjects for r in rows], 10_000)
    ranked = await rerank.rerank_hits(tenant_id, text_query, pool, RETRIEVE)
    hits = cover_subjects(ranked.hits, found.subjects, RETRIEVE)
    found.hits = _boost(found.focus_hits, hits, RETRIEVE)
    found.reranked = ranked.reranked
    return found


async def graph_phase(
    session: AsyncSession, user: UUID, route: Route, hits: Sequence[dict[str, Any]]
) -> list[Excerpt]:
    return await graph.expand(session, user, [h["id"] for h in hits], route.intent)
