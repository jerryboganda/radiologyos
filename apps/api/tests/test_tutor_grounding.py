"""Citation enforcement for the grounded tutor (hard rule 3, ADR 0013)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from packages.tutor.grounding import (
    NOT_FOUND,
    NOT_FOUND_AFTER_WEB,
    Excerpt,
    combine,
    excerpts_from_hits,
    ground_sources,
    ground_web,
    grounding_of,
    verified_url,
)
from packages.tutor.models import (
    Citation,
    GroundedAnswer,
    Segment,
    SourceAnswer,
    SourceSegment,
    WebAnswer,
    WebSegment,
)
from pydantic import ValidationError


def _excerpts(n: int = 2) -> list[Excerpt]:
    hits = [
        {"id": uuid4(), "source_id": uuid4(), "source_title": f"Deck {i}", "page_from": i,
         "page_to": i, "heading": "", "text": f"text {i}", "block_refs": [{"page": i, "block": 0}]}
        for i in range(1, n + 1)
    ]
    return excerpts_from_hits(hits)


def _src(*segments: tuple[str, list[str]], coverage: str = "full") -> SourceAnswer:
    return SourceAnswer.model_validate(
        {"segments": [{"text": t, "sources": s} for t, s in segments], "coverage": coverage}
    )


def test_excerpts_are_labelled_in_rank_order_with_provenance() -> None:
    excerpts = _excerpts(3)
    assert [e.label for e in excerpts] == ["S1", "S2", "S3"]
    citation = excerpts[1].citation()
    assert citation.kind == "source" and citation.page_from == 2
    assert citation.block_refs == [{"page": 2, "block": 0}]


def test_valid_labels_map_to_retrieved_chunk_ids() -> None:
    excerpts = _excerpts()
    kept, dropped = ground_sources(_src(("Crazy paving.", ["S1", "S2"])), excerpts)
    assert dropped == 0
    assert [c.chunk_id for c in kept[0].citations] == [excerpts[0].chunk_id, excerpts[1].chunk_id]
    assert kept[0].origin == "sources"


def test_labels_are_normalised_and_deduplicated() -> None:
    excerpts = _excerpts()
    kept, _ = ground_sources(_src(("A.", ["s1", "[S1]", " S1 "])), excerpts)
    assert len(kept[0].citations) == 1 and kept[0].citations[0].label == "S1"


def test_segments_citing_only_unretrieved_labels_are_dropped() -> None:
    excerpts = _excerpts()
    answer = _src(("Supported.", ["S2"]), ("Invented.", ["S9"]), ("Uncited.", []))
    kept, dropped = ground_sources(answer, excerpts)
    assert [s.text for s in kept] == ["Supported."]
    assert dropped == 2


def test_model_supplied_chunk_ids_are_never_trusted() -> None:
    excerpts = _excerpts()
    forged = str(uuid4())
    kept, dropped = ground_sources(_src(("Forged.", [forged])), excerpts)
    assert kept == [] and dropped == 1
    kept, _ = ground_sources(_src(("Mixed.", [forged, "S1"])), excerpts)
    assert [c.chunk_id for c in kept[0].citations] == [excerpts[0].chunk_id]


def test_whitespace_only_text_is_dropped_and_text_is_collapsed() -> None:
    kept, dropped = ground_sources(_src(("   ", ["S1"]), ("a\n  b", ["S1"])), _excerpts())
    assert dropped == 1 and kept[0].text == "a b"


@pytest.mark.parametrize(
    "url",
    [
        "https://radiopaedia.org/articles/crazy-paving",
        "https://pubs.rsna.org/doi/10.1148/rg.123",
        "https://www.ajronline.org/doi/full/10.2214/AJR.1",
        "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
        "https://www.rcr.ac.uk/exams",
        "https://www.cpsp.edu.pk/fcps-ii",
        "https://RADIOPAEDIA.org:443/cases/1",
    ],
)
def test_allow_listed_https_urls_verify(url: str) -> None:
    assert verified_url(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://radiopaedia.org/articles/x",
        "https://radiopaedia.org.evil.example/x",
        "https://notradiopaedia.org/x",
        "https://user:pw@radiopaedia.org/x",
        "https://radiopaedia.org:8443/x",
        "javascript:alert(1)",
        "ftp://radiopaedia.org/x",
        "https://example.com/?u=https://radiopaedia.org",
        "",
        "radiopaedia.org/articles/x",
        "https://[::1/x",
    ],
)
def test_other_urls_are_rejected(url: str) -> None:
    assert verified_url(url) is None


def test_verified_url_normalises_host_and_drops_fragment() -> None:
    assert verified_url("https://Radiopaedia.org/a?b=1#frag") == "https://radiopaedia.org/a?b=1"


def test_ground_web_keeps_only_allow_listed_citations() -> None:
    answer = WebAnswer(segments=[
        WebSegment(text="Good.", urls=["https://radiopaedia.org/a", "https://evil.example/b",
                                       "https://radiopaedia.org/a#x"]),
        WebSegment(text="Bad.", urls=["https://evil.example/c"]),
        WebSegment(text="None.", urls=[]),
    ])
    kept, dropped = ground_web(answer)
    assert dropped == 2
    assert [c.url for c in kept[0].citations] == ["https://radiopaedia.org/a"]
    assert kept[0].origin == "web"


def _seg(origin: str) -> Segment:
    citation = (Citation(kind="web", url="https://radiopaedia.org/a") if origin == "web"
                else Citation(kind="source", label="S1", chunk_id=uuid4()))
    return Segment(text=origin, origin=origin, citations=[citation])


def test_grounding_label_reflects_segment_origins() -> None:
    assert grounding_of([]) == "none"
    assert grounding_of([_seg("sources")]) == "sources"
    assert grounding_of([_seg("web")]) == "web"
    assert grounding_of([_seg("sources"), _seg("web")]) == "mixed"


def test_combine_orders_sources_before_web() -> None:
    result = combine([_seg("sources")], [_seg("web")], 1, web_attempted=True, agent_version="v")
    assert [s.origin for s in result.segments] == ["sources", "web"]
    assert (result.grounding, result.dropped_segments, result.notice) == ("mixed", 1, None)


def test_nothing_valid_returns_not_found_notice() -> None:
    result = combine([], [], 3, web_attempted=False)
    assert (result.grounding, result.notice, result.segments) == ("none", NOT_FOUND, [])
    assert result.text == NOT_FOUND
    after_web = combine([], [], 0, web_attempted=True)
    assert after_web.notice == NOT_FOUND_AFTER_WEB


def test_segment_without_citation_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError):
        Segment(text="uncited", origin="sources", citations=[])


def test_grounded_answer_text_joins_segments() -> None:
    answer = GroundedAnswer(segments=[_seg("sources"), _seg("web")], grounding="mixed")
    assert answer.text == "sources web"


def test_agent_outputs_reject_extra_fields_and_bad_coverage() -> None:
    with pytest.raises(ValidationError):
        SourceAnswer.model_validate({"segments": [], "coverage": "most"})
    with pytest.raises(ValidationError):
        SourceSegment.model_validate({"text": "x", "sources": ["S1"], "chunk_id": "y"})
    with pytest.raises(ValidationError):
        WebSegment.model_validate({"text": "", "urls": []})


def test_excerpt_citation_ids_are_uuids() -> None:
    excerpt = _excerpts(1)[0]
    assert isinstance(excerpt.citation().chunk_id, UUID)
