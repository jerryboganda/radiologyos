"""Assemble the packaged radiology curriculum from its per-system files.

``radiology/pack.json`` holds the pack metadata and the ordered list of system
files; each system file nests its topics and subtopics with code *suffixes*
(``{"code": "PE", ...}`` under ``PULM_VASC`` under ``CHEST`` becomes
``CHEST.PULM_VASC.PE``). A node without ``exams`` inherits its parent's tags.
The flattened result is validated as a schema-version-2 ``CurriculumPack``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from packages.curriculum.contracts import CurriculumNode, CurriculumPack, pack_hash

PACK_DIR = Path(__file__).resolve().parent / "radiology"


def _read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _system_nodes(root: str, system: dict[str, Any]) -> list[dict[str, Any]]:
    code, exams = system["code"], list(system["exams"])
    nodes = [{"code": code, "parent_code": root, "level": "system",
              "title": system["title"], "exams": exams}]
    for topic in system.get("topics", []):
        topic_code = f"{code}.{topic['code']}"
        topic_exams = list(topic.get("exams") or exams)
        nodes.append({"code": topic_code, "parent_code": code, "level": "topic",
                      "title": topic["title"], "exams": topic_exams})
        for suffix, title in topic.get("subtopics", {}).items():
            nodes.append({"code": f"{topic_code}.{suffix}", "parent_code": topic_code,
                          "level": "subtopic", "title": title, "exams": topic_exams})
    return nodes


def load_pack(directory: Path = PACK_DIR) -> CurriculumPack:
    """Flatten and validate the pack in ``directory``."""
    manifest = _read(directory / "pack.json")
    root = manifest["root"]
    nodes: list[dict[str, Any]] = [
        {"code": root["code"], "parent_code": None, "level": "section", "title": root["title"]}
    ]
    for name in manifest["systems"]:
        nodes.extend(_system_nodes(root["code"], _read(directory / name)))
    fields = {k: v for k, v in manifest.items() if k not in ("root", "systems")}
    return CurriculumPack.model_validate({**fields, "nodes": nodes})


@lru_cache(maxsize=1)
def radiology_pack() -> CurriculumPack:
    return load_pack()


@lru_cache(maxsize=1)
def radiology_hash() -> str:
    return pack_hash(radiology_pack())


@lru_cache(maxsize=1)
def node_index() -> dict[str, CurriculumNode]:
    return {node.code: node for node in radiology_pack().nodes}


def system_of(code: str) -> str | None:
    """The system code a node belongs to (itself for a system), else None."""
    index = node_index()
    node = index.get(code)
    while node is not None and node.level not in ("system", "section"):
        node = index.get(node.parent_code or "")
    return node.code if node is not None and node.level == "system" else None
