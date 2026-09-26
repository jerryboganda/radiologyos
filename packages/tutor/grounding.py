"""Citation enforcement for the tutor (hard rule 3, ADR 0013).

The model's citations are claims, not facts. Every segment is kept only if at
least one of its citations verifies:

* a source label must name an excerpt retrieved for *this* question from the
  caller's own library (labels are mapped back to chunk ids here, never taken
  from model output);
* a web citation must be an https URL, without credentials, on an allow-listed
  authoritative radiology domain.

Segments with no verified citation are dropped and counted. If nothing
survives, the answer is an explicit "not found in your sources" notice with
grounding ``none`` — never uncited tutor text.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from packages.tutor.models import (
    Citation,
    GroundedAnswer,
    Grounding,
    Segment,
    SourceAnswer,
    WebAnswer,
)

NOT_FOUND = (
    "Not found in your sources: none of your uploaded material covers this question, "
    "so no answer is given."
)
NOT_FOUND_AFTER_WEB = (
    "Not found in your sources, and no answer could be verified against the "
    "authoritative radiology references either."
)

# Authoritative radiology references (ADR 0011, ADR 0013). A URL passes when
# its host is one of these or a subdomain of one.
ALLOWED_WEB_DOMAINS: tuple[str, ...] = (
    "radiopaedia.org",
    "rsna.org",  # includes pubs.rsna.org (RadioGraphics, Radiology)
    "ajronline.org",
    "rcr.ac.uk",
    "acr.org",
    "cpsp.edu.pk",
    "ncbi.nlm.nih.gov",  # includes pubmed.ncbi.nlm.nih.gov and PMC
)


@dataclass(frozen=True, slots=True)
class Excerpt:
    """One retrieved chunk as shown to the model, under a short label."""

    label: str
    chunk_id: UUID
    source_id: UUID
    source_title: str
    page_from: int
    page_to: int
    heading: str
    text: str
    block_refs: list[dict[str, int]] = field(default_factory=list)

    def citation(self) -> Citation:
        return Citation(
            kind="source", label=self.label, chunk_id=self.chunk_id,
            source_id=self.source_id, source_title=self.source_title,
            page_from=self.page_from, page_to=self.page_to, block_refs=self.block_refs,
        )


def excerpts_from_hits(hits: Sequence[dict[str, Any]]) -> list[Excerpt]:
    """Label retrieval hits S1..Sn in rank order."""
    return [
        Excerpt(
            label=f"S{rank}", chunk_id=hit["id"], source_id=hit["source_id"],
            source_title=hit["source_title"], page_from=hit["page_from"],
            page_to=hit["page_to"], heading=hit.get("heading") or "", text=hit["text"],
            block_refs=list(hit.get("block_refs") or []),
        )
        for rank, hit in enumerate(hits, start=1)
    ]


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def ground_sources(
    answer: SourceAnswer, excerpts: Sequence[Excerpt]
) -> tuple[list[Segment], int]:
    """Keep segments whose labels resolve to retrieved excerpts."""
    by_label = {excerpt.label.upper(): excerpt for excerpt in excerpts}
    kept: list[Segment] = []
    dropped = 0
    for segment in answer.segments:
        text = _clean_text(segment.text)
        seen: dict[str, Excerpt] = {}
        for label in segment.sources:
            found = by_label.get(label.strip().strip("[]").upper())
            if found is not None:
                seen.setdefault(found.label, found)
        if not text or not seen:
            dropped += 1
            continue
        kept.append(Segment(text=text, origin="sources",
                            citations=[e.citation() for e in seen.values()]))
    return kept, dropped


def verified_url(url: str, allowed: Iterable[str] = ALLOWED_WEB_DOMAINS) -> str | None:
    """Return a normalised URL if it is https on an allowed domain, else None."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    if port not in (None, 443):
        return None
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        return None
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"https://{host}{path}{query}"


def ground_web(
    answer: WebAnswer, allowed: Iterable[str] = ALLOWED_WEB_DOMAINS
) -> tuple[list[Segment], int]:
    """Keep segments with at least one allow-listed https citation."""
    domains = tuple(allowed)
    kept: list[Segment] = []
    dropped = 0
    for segment in answer.segments:
        text = _clean_text(segment.text)
        urls = list(dict.fromkeys(u for u in (verified_url(x, domains) for x in segment.urls)
                                  if u is not None))
        if not text or not urls:
            dropped += 1
            continue
        kept.append(Segment(text=text, origin="web",
                            citations=[Citation(kind="web", url=u) for u in urls]))
    return kept, dropped


def grounding_of(segments: Sequence[Segment]) -> Grounding:
    origins = {segment.origin for segment in segments}
    if not origins:
        return "none"
    if origins == {"sources"}:
        return "sources"
    if origins == {"web"}:
        return "web"
    return "mixed"


def combine(
    source_segments: Sequence[Segment],
    web_segments: Sequence[Segment],
    dropped: int,
    *,
    web_attempted: bool,
    notice: str | None = None,
    agent_version: str = "",
) -> GroundedAnswer:
    """Source-cited segments first, then web segments, each labelled by origin."""
    segments = [*source_segments, *web_segments]
    for segment in segments:
        if not segment.citations:  # defensive: Segment already requires one
            raise ValueError("uncited segment reached the final answer")
    if not segments:
        notice = notice or (NOT_FOUND_AFTER_WEB if web_attempted else NOT_FOUND)
    return GroundedAnswer(
        segments=segments, grounding=grounding_of(segments), dropped_segments=dropped,
        notice=notice, agent_version=agent_version,
    )
