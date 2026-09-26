"""Read a rendered vault back: ids, wikilinks, and citations (M7 round trip).

The inverse of :mod:`vault` for everything a re-import needs: each file's
``radbrain_id``, every ``[[target|alias]]`` link with whether it resolves to a
file in the vault, and every ``Source: [[sources/..|..]], p. N`` citation
resolved to the cited source's id and page range.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from apps.worker.app.datarights.vault import ROOT

LINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
CITE = re.compile(
    r"Source: \[\[(sources/[^\[\]|#]+)\|[^\[\]]*\]\], (?:p\. (\d+)|pp\. (\d+)-(\d+))"
    r"(?: \(blocks ((?:p\d+-b\d+)(?:, p\d+-b\d+)*)\))?"
)
BLOCK = re.compile(r"p(\d+)-b(\d+)")
RADBRAIN_ID = re.compile(r'^radbrain_id: "([0-9a-f-]{36})"$', re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Citation:
    file: str
    source_id: UUID
    page_from: int
    page_to: int
    blocks: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class VaultIndex:
    ids: dict[str, UUID] = field(default_factory=dict)
    links: list[tuple[str, str]] = field(default_factory=list)
    broken: list[tuple[str, str]] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)


def _target_path(target: str) -> str:
    return f"{ROOT}/{target.strip()}.md"


def read_vault(files: Mapping[str, str]) -> VaultIndex:
    index = VaultIndex()
    for path, body in files.items():
        found = RADBRAIN_ID.search(body)
        if found:
            index.ids[path] = UUID(found.group(1))
    for path, body in files.items():
        for match in LINK.finditer(body):
            target = _target_path(match.group(1))
            index.links.append((path, target))
            if target not in files:
                index.broken.append((path, target))
        for match in CITE.finditer(body):
            source_path = _target_path(match.group(1))
            source_id = index.ids.get(source_path)
            if source_id is None:
                index.broken.append((path, source_path))
                continue
            first = int(match.group(2) or match.group(3))
            last = int(match.group(2) or match.group(4))
            blocks = tuple((int(p), int(b)) for p, b in BLOCK.findall(match.group(5) or ""))
            index.citations.append(Citation(path, source_id, first, last, blocks))
    return index
