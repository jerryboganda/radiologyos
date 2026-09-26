"""Concept-note synthesis: prompt, claims hash, and fail-closed citation checks.

The Synthesis agent sees only one concept's own claims, each labelled ``C1``..
``Cn``. Every sentence it returns must cite labels that were supplied, and must
be lexically supported by the cited claims: its content words mostly appear in
them, every number it states appears in them, and it negates only when a cited
claim does. A sentence that fails any check is dropped, never stored (spec
section 5; hard rule 3). A differential with no surviving discriminator is
dropped too. Nothing here calls a model or touches the database.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from packages.knowledge.agents import ConceptNote, NoteSentence
from packages.knowledge.conflicts import content_words, numbers
from packages.knowledge.text import normalize_name

MAX_CLAIMS = 60
SUPPORT = 0.5
_NEGATIONS = frozenset({"no", "not", "never", "without", "absent", "absence", "none", "cannot"})


def claims_hash(claims: Sequence[Mapping[str, Any]]) -> str:
    """Stable hash of the claims a note is built from (regenerate when it changes)."""
    parts = sorted(f"{c['id']}|{c['status']}|{c['statement']}" for c in claims)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def label_claims(claims: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """``C1``.. labels for the most important claims (capped)."""
    ranked = sorted(claims, key=lambda c: (-int(c.get("importance") or 0), str(c["id"])))
    return {f"C{n}": claim for n, claim in enumerate(ranked[:MAX_CLAIMS], start=1)}


def build_prompt(concept: Mapping[str, Any], labels: Mapping[str, Mapping[str, Any]],
                 differentials: Sequence[str]) -> str:
    lines = [f"Concept: {concept['name']} ({concept.get('concept_type') or 'other'})"]
    if concept.get("aliases"):
        lines.append(f"Aliases: {', '.join(concept['aliases'])}")
    if differentials:
        lines.append(f"Linked differentials in the graph: {', '.join(differentials)}")
    lines.append("\nClaims (the only facts you may use):")
    for label, claim in labels.items():
        extra = [str(claim.get("claim_type") or "other")]
        if claim.get("modality"):
            extra.append(str(claim["modality"]))
        if claim.get("status") == "disputed":
            extra.append("DISPUTED by another source")
        lines.append(f"[{label}] ({'; '.join(extra)}) {claim['statement']}")
    return "\n".join(lines)


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in content_words(text)}


def _negated(text: str) -> bool:
    return any(word in _NEGATIONS for word in text.lower().replace("n't", " not").split())


def supported(sentence: str, cited: Sequence[str]) -> bool:
    """Lexical support of a sentence by the text of the claims it cites."""
    evidence = " ".join(cited)
    words = _words(sentence)
    if words and len(words & _words(evidence)) / len(words) < SUPPORT:
        return False
    found = numbers(evidence)
    for unit, values in numbers(sentence).items():
        if not values <= found.get(unit, set()):
            return False
    return not (_negated(sentence) and not any(_negated(text) for text in cited))


@dataclass(slots=True)
class CheckedNote:
    body: dict[str, Any]
    kept: int = 0
    dropped: int = 0
    claim_ids: list[str] = field(default_factory=list)


class _Checker:
    def __init__(self, labels: Mapping[str, Mapping[str, Any]]) -> None:
        self.labels = labels
        self.result = CheckedNote(body={})

    def sentences(self, items: Sequence[NoteSentence]) -> list[dict[str, Any]]:
        kept = []
        for item in items:
            refs = [ref.strip().strip("[]") for ref in item.cites]
            claims = [self.labels[r] for r in dict.fromkeys(refs) if r in self.labels]
            cited = [f"{c['statement']} {c.get('evidence_span') or ''}" for c in claims]
            if not claims or len(claims) != len(set(refs)) or not supported(item.text, cited):
                self.result.dropped += 1
                continue
            ids = [str(c["id"]) for c in claims]
            self.result.kept += 1
            self.result.claim_ids.extend(i for i in ids if i not in self.result.claim_ids)
            kept.append({"text": item.text.strip(), "claim_ids": ids})
        return kept


def check_note(note: ConceptNote, labels: Mapping[str, Mapping[str, Any]],
               differential_ids: Mapping[str, str] | None = None) -> CheckedNote:
    """Keep only cited, supported sentences; map labels back to claim ids."""
    checker = _Checker(labels)
    ddx_ids = differential_ids or {}
    body: dict[str, Any] = {
        "definition": checker.sentences(note.definition),
        "imaging": [],
        "differentials": [],
        "pearls": checker.sentences(note.pearls),
        "pitfalls": checker.sentences(note.pitfalls),
    }
    for group in note.imaging:
        sentences = checker.sentences(group.sentences)
        if sentences:
            body["imaging"].append({"modality": group.modality.strip(), "sentences": sentences})
    for item in note.differentials:
        discriminators = checker.sentences(item.discriminators)
        if not discriminators:
            continue
        key = normalize_name(item.name)
        body["differentials"].append({"name": item.name.strip(), "concept_id": ddx_ids.get(key),
                                      "discriminators": discriminators})
    checker.result.body = body
    return checker.result


def note_problem(note: ConceptNote, labels: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Quality gate for the gateway's ``accept=``: fixed reason strings only."""
    checked = check_note(note, labels)
    if checked.kept == 0:
        return "no_supported_sentences"
    if checked.dropped > checked.kept:
        return "mostly_unsupported"
    return None
