"""Semantic grounding judge for tutor answers (hard rule 3, ADR 0013 v2).

The structural check in ``grounding`` proves that every citation names
evidence retrieved for this question; it cannot prove that the evidence says
what the segment claims. ``grounding_judge`` (classify route, no tools) reads
each segment beside the text of exactly the evidence it cites and returns
supported | partial | unsupported:

* unsupported segments are dropped and counted;
* partial segments are kept with a visible "partially supported" label;
* supported segments are kept as they are;
* if the judge is switched off, its call fails, or it returns no verdict for a
  segment, the segment is kept but labelled "not verified" — never presented
  as verified.

Web segments are judged against the web agent's summary of the pages they
cite when one exists; otherwise they stay labelled "From the web" only.
Nothing here logs segment or evidence text (hard rule 4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from packages.models.claude_code import ModelCallError
from packages.models.gateway import Transport, load_agent, run_agent
from packages.tutor.grounding import Citable, FigureExcerpt
from packages.tutor.models import JudgeStats, JudgeVerdicts, Segment, SegmentVerdict

JUDGE_AGENT = "grounding_judge"
EVIDENCE_CHARS = 4000
StatusCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Evidence:
    """Citable text under a label: S/F from retrieval, W for summarised web pages."""

    label: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class Item:
    """One segment to judge: its number in the prompt and the evidence it cites."""

    number: int
    segment: Segment
    labels: tuple[str, ...]


def _escape(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def evidence_index(
    citables: Sequence[Citable], summaries: Mapping[str, str]
) -> tuple[dict[str, Evidence], dict[str, str]]:
    """Evidence by label, plus the W label assigned to each summarised URL."""
    evidence = {
        c.label: Evidence(c.label, "figure description" if isinstance(c, FigureExcerpt)
                          else "excerpt", c.evidence)
        for c in citables
    }
    url_labels: dict[str, str] = {}
    for n, (url, summary) in enumerate(summaries.items(), start=1):
        label = f"W{n}"
        evidence[label] = Evidence(label, "web page summary", summary)
        url_labels[url] = label
    return evidence, url_labels


def plan(
    segments: Sequence[Segment], evidence: Mapping[str, Evidence], url_labels: Mapping[str, str]
) -> dict[int, Item]:
    """Segments (by index) that have at least one piece of citable evidence text."""
    items: dict[int, Item] = {}
    for index, segment in enumerate(segments):
        labels: list[str] = []
        for citation in segment.citations:
            label = url_labels.get(citation.url or "") if citation.kind == "web" else citation.label
            if label and label in evidence and label not in labels:
                labels.append(label)
        if labels:
            items[index] = Item(len(items) + 1, segment, tuple(labels))
    return items


def judge_prompt(items: Sequence[Item], evidence: Mapping[str, Evidence]) -> str:
    cited = list(dict.fromkeys(label for item in items for label in item.labels))
    blocks = [
        f'<item id="{label}" kind="{evidence[label].kind}">\n'
        f"{_escape(evidence[label].text[:EVIDENCE_CHARS])}\n</item>"
        for label in cited
    ]
    segments = [
        f'<segment n="{item.number}" cites="{" ".join(item.labels)}">'
        f"{_escape(item.segment.text)}</segment>"
        for item in items
    ]
    return ("<evidence>\n" + "\n".join(blocks) + "\n</evidence>\n\n"
            + "<segments>\n" + "\n".join(segments) + "\n</segments>")


def apply_verdicts(
    segments: Sequence[Segment], items: Mapping[int, Item],
    verdicts: Sequence[SegmentVerdict] | None, stats: JudgeStats,
) -> tuple[list[Segment], JudgeStats]:
    """Drop unsupported segments and label the rest; count every outcome."""
    by_number: dict[int, SegmentVerdict] = {}
    for verdict in verdicts or ():
        by_number.setdefault(verdict.segment, verdict)
    kept: list[Segment] = []
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "not_verified": 0,
              "web_unjudged": 0}
    for index, segment in enumerate(segments):
        item = items.get(index)
        if item is None:
            counts["web_unjudged" if segment.origin == "web" else "not_verified"] += 1
            kept.append(segment if segment.origin == "web"
                        else segment.model_copy(update={"support": "not_verified"}))
            continue
        found = by_number.get(item.number)
        outcome = found.verdict if found is not None else "not_verified"
        counts[outcome] += 1
        if outcome == "unsupported":
            continue
        note = None
        if found is not None and outcome == "partial":
            note = found.reason.strip() or None
        kept.append(segment.model_copy(update={"support": outcome, "support_note": note}))
    return kept, stats.model_copy(update={"judged": len(items), **counts})


def judge_segments(
    transport: Transport,
    segments: Sequence[Segment],
    citables: Sequence[Citable],
    summaries: Mapping[str, str],
    *,
    enabled: bool = True,
    on_status: StatusCallback | None = None,
) -> tuple[list[Segment], JudgeStats]:
    """Run the judge over every segment that has evidence text; see module doc."""
    evidence, url_labels = evidence_index(citables, summaries)
    items = plan(segments, evidence, url_labels)
    if not items:
        return apply_verdicts(segments, items, None, JudgeStats(status="not_run"))
    if not enabled:
        return apply_verdicts(segments, items, None, JudgeStats(status="skipped"))
    if on_status is not None:
        on_status("judging")
    version = load_agent(JUDGE_AGENT).key
    try:
        parsed, _ = run_agent(transport, JUDGE_AGENT, judge_prompt(list(items.values()), evidence))
    except ModelCallError:  # includes UsageLimitError: keep segments, label not verified
        return apply_verdicts(segments, items, None,
                              JudgeStats(status="failed", agent_version=version))
    verdicts = cast(JudgeVerdicts, parsed).verdicts
    return apply_verdicts(segments, items, verdicts, JudgeStats(status="ok", agent_version=version))
