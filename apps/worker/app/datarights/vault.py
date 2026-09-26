"""Obsidian-compatible Markdown vault of one user's knowledge (M7 portability).

Part of the account export (ADR 0018, ADR 0031). Pure: rows in, ``{path: text}``
out, byte-stable for the same rows. Layout under ``vault/``:

* ``index.md`` links every concept, source, and card deck;
* ``concepts/<slug>.md`` holds the concept's cited claims and its related
  concepts as ``[[wikilinks]]``;
* ``sources/<slug>.md`` names one uploaded source and back-links its concepts;
* ``cards/<slug>.md`` holds the study cards of one curriculum code.

Every file starts with YAML front matter carrying its ``radbrain_id`` so a
re-import can map files back to rows. File names end in the first eight hex
digits of the row id, so two rows with the same title never share a file.
Every claim and card cites its source as ``[[sources/<slug>|Title]], p. N``
(or ``pp. A-B``), and a claim adds its evidence blocks as ``(blocks p3-b4)``
so provenance resolves to the page block and its bounding box;
:mod:`vault_links` parses all of that back. User text is escaped so it can
never forge a link, block id, tag, comment, or HTML.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = "vault"
_SLUG = re.compile(r"[^a-z0-9]+")
_ESCAPE = re.compile(r"([\\\[\]^%<>`#|*_])")
_ALIAS_UNSAFE = re.compile(r"[\[\]|#^\\]+")


@dataclass(frozen=True, slots=True)
class VaultSource:
    id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class VaultConcept:
    id: UUID
    name: str
    concept_type: str = "other"
    aliases: tuple[str, ...] = ()
    curriculum_code: str | None = None


@dataclass(frozen=True, slots=True)
class VaultClaim:
    id: UUID
    concept_id: UUID
    statement: str
    evidence: str
    status: str
    source_id: UUID
    page_from: int
    page_to: int
    blocks: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class VaultEdge:
    from_concept: UUID
    to_concept: UUID
    relation: str


@dataclass(frozen=True, slots=True)
class VaultCard:
    id: UUID
    curriculum_code: str
    topic: str
    front: str
    back: str
    source_id: UUID | None
    page_from: int | None
    page_to: int | None


@dataclass(frozen=True, slots=True)
class VaultRows:
    sources: Sequence[VaultSource] = ()
    concepts: Sequence[VaultConcept] = ()
    claims: Sequence[VaultClaim] = ()
    edges: Sequence[VaultEdge] = ()
    cards: Sequence[VaultCard] = ()


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def escape(value: object) -> str:
    """One line of user text that Markdown and Obsidian render literally."""
    return _ESCAPE.sub(r"\\\1", one_line(value))


def unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def slug(name: str, row_id: UUID) -> str:
    base = _SLUG.sub("-", one_line(name).lower()).strip("-")[:60].strip("-")
    return f"{base or 'untitled'}-{row_id.hex[:8]}"


def pages(page_from: int | None, page_to: int | None) -> str:
    if page_from is None:
        return "page unknown"
    end = page_to if page_to is not None else page_from
    return f"p. {page_from}" if end == page_from else f"pp. {page_from}-{end}"


def wikilink(target: str, name: str) -> str:
    alias = " ".join(_ALIAS_UNSAFE.sub(" ", one_line(name)).split()) or "untitled"
    return f"[[{target}|{alias}]]"


def link(folder: str, name: str, row_id: UUID) -> str:
    return wikilink(f"{folder}/{slug(name, row_id)}", name)


def front_matter(kind: str, row_id: UUID, title: str, **extra: object) -> list[str]:
    lines = ["---", f"radbrain_id: {json.dumps(str(row_id))}", f"type: {kind}",
             f"title: {json.dumps(one_line(title), ensure_ascii=False)}"]
    for key, value in extra.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return [*lines, "---", ""]


def _citation(sources: dict[UUID, VaultSource], source_id: UUID | None,
              page_from: int | None, page_to: int | None,
              blocks: tuple[tuple[int, int], ...] = ()) -> str:
    source = sources.get(source_id) if source_id else None
    if source is None:
        return f"Source: deleted source, {pages(page_from, page_to)}"
    cited = f"Source: {link('sources', source.title, source.id)}, {pages(page_from, page_to)}"
    if blocks:
        cited += " (blocks " + ", ".join(f"p{p}-b{b}" for p, b in blocks) + ")"
    return cited


def _concept_file(concept: VaultConcept, claims: Iterable[VaultClaim],
                  related: Iterable[tuple[str, VaultConcept]],
                  sources: dict[UUID, VaultSource]) -> str:
    lines = front_matter("concept", concept.id, concept.name,
                         concept_type=concept.concept_type,
                         aliases=[one_line(a) for a in concept.aliases],
                         curriculum_code=concept.curriculum_code)
    lines += [f"# {escape(concept.name)}", "", "## Claims", ""]
    for claim in claims:
        status = "" if claim.status == "active" else f" ({escape(claim.status)})"
        lines += [
            f"- {escape(claim.statement)}{status} ^claim-{claim.id.hex}",
            f"  - Evidence: \"{escape(claim.evidence)}\"",
            f"  - {_citation(sources, claim.source_id, claim.page_from, claim.page_to,
                             claim.blocks)}",
        ]
    edges = list(related)
    if edges:
        lines += ["", "## Related", ""]
        lines += [f"- {escape(rel)}: {link('concepts', other.name, other.id)}"
                  for rel, other in edges]
    return "\n".join(lines) + "\n"


def _source_file(source: VaultSource, cited_by: Iterable[VaultConcept]) -> str:
    lines = front_matter("source", source.id, source.title)
    lines += [f"# {escape(source.title)}", "", "## Concepts cited from this source", ""]
    lines += [f"- {link('concepts', c.name, c.id)}" for c in cited_by]
    return "\n".join(lines) + "\n"


def _deck_file(code: str, cards: Iterable[VaultCard],
               sources: dict[UUID, VaultSource]) -> str:
    deck_id = uuid5(NAMESPACE_URL, f"radbrain:card-deck:{code}")
    lines = front_matter("cards", deck_id, code, curriculum_code=code)
    lines += [f"# Cards: {escape(code)}", ""]
    for card in cards:
        lines += [
            f"## {escape(card.topic)} ^card-{card.id.hex}", "",
            f"**Q:** {escape(card.front)}", "",
            f"**A:** {escape(card.back)}", "",
            f"_{_citation(sources, card.source_id, card.page_from, card.page_to)}_", "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def deck_path(code: str) -> str:
    base = _SLUG.sub("-", one_line(code).lower()).strip("-") or "uncoded"
    return f"{ROOT}/cards/{base}.md"


def render_vault(rows: VaultRows) -> dict[str, str]:
    """Render the vault; files, entries, and links are in a stable order."""
    sources = {s.id: s for s in sorted(rows.sources, key=lambda s: (s.title, s.id))}
    claims = sorted((c for c in rows.claims if c.source_id in sources),
                    key=lambda c: (c.page_from, c.statement, c.id))
    cited = {c.concept_id for c in claims}
    concepts = {c.id: c for c in sorted(rows.concepts, key=lambda c: (c.name, c.id))
                if c.id in cited}
    files: dict[str, str] = {}
    for concept in concepts.values():
        mine = [c for c in claims if c.concept_id == concept.id]
        related = sorted(((e.relation, concepts[e.to_concept]) for e in rows.edges
                          if e.from_concept == concept.id and e.to_concept in concepts),
                         key=lambda pair: (pair[0], pair[1].name, pair[1].id))
        path = f"{ROOT}/concepts/{slug(concept.name, concept.id)}.md"
        files[path] = _concept_file(concept, mine, related, sources)
    for source in sources.values():
        cited_by = [concepts[cid] for cid in dict.fromkeys(
            c.concept_id for c in claims if c.source_id == source.id) if cid in concepts]
        cited_by.sort(key=lambda c: (c.name, c.id))
        files[f"{ROOT}/sources/{slug(source.title, source.id)}.md"] = _source_file(
            source, cited_by)
    decks: dict[str, list[VaultCard]] = {}
    for card in sorted(rows.cards, key=lambda c: (c.curriculum_code, c.topic, c.id)):
        decks.setdefault(card.curriculum_code, []).append(card)
    for code, cards in decks.items():
        files[deck_path(code)] = _deck_file(code, cards, sources)
    files[f"{ROOT}/index.md"] = _index(concepts.values(), sources.values(), decks)
    return dict(sorted(files.items()))


def _index(concepts: Iterable[VaultConcept], sources: Iterable[VaultSource],
           decks: dict[str, list[VaultCard]]) -> str:
    lines = ["# radbrain knowledge vault", "",
             "Every claim and card cites its source and page. Open this folder as an",
             "Obsidian vault, or read the files as plain Markdown.", "", "## Concepts", ""]
    lines += [f"- {link('concepts', c.name, c.id)}" for c in concepts] or ["- (none yet)"]
    lines += ["", "## Sources", ""]
    lines += [f"- {link('sources', s.title, s.id)}" for s in sources] or ["- (none yet)"]
    lines += ["", "## Card decks", ""]
    deck_lines = [f"- {wikilink(deck_path(code)[len(ROOT) + 1:-3], code)} ({len(cards)} cards)"
                  for code, cards in decks.items()]
    lines += deck_lines or ["- (none yet)"]
    return "\n".join(lines) + "\n"
