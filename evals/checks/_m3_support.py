"""Synthetic corpus and evidence-bound model fakes for the M3 tutor gate.

``Corpus`` replaces only the SQL leaves of ``apps.api.app.library.search``
(``lexical``, ``dense``, ``hydrate``) so the durable ``hybrid_search`` (RRF
fusion and the top-k cut) really runs. Its rows model RLS plus the
``uploaded_by`` filter: a query sees only the calling tenant's rows uploaded by
the calling user. ``EvidenceTransport`` extends the shared tutor fake
(``apps/api/tests/tutor_fakes.py``): the tutor agent answers with sentences
copied from the excerpts it was shown (plus any ``extra`` segments a test
injects), and the grounding judge marks a segment supported only when its text
appears in the evidence it cites. Deterministic; no database, no network.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.library import search
from apps.api.app.security.principal import Principal
from apps.api.tests.tutor_fakes import FakeTransport, agent_of
from packages.models.claude_code import ModelCall

REAL_HYBRID_SEARCH = search.hybrid_search
TENANT_A = UUID("30000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("30000000-0000-4000-8000-00000000000b")
TENANT_C = UUID("30000000-0000-4000-8000-00000000000c")
USER_A = Principal(UUID("10000000-0000-4000-8000-00000000000a"), TENANT_A)
USER_A2 = Principal(UUID("10000000-0000-4000-8000-0000000000a2"), TENANT_A)
USER_B = Principal(UUID("10000000-0000-4000-8000-00000000000b"), TENANT_B)
USER_C = Principal(UUID("10000000-0000-4000-8000-00000000000c"), TENANT_C)
CHEST = [
    "Blunting of the costophrenic angle suggests a small pleural effusion on an erect chest "
    "radiograph. About 200 ml of fluid is needed before the lateral angle blunts.",
    "Bilateral hilar lymphadenopathy with perilymphatic nodules is typical of sarcoidosis. "
    "Eggshell calcification of the hilar nodes may follow.",
]
HEAD = ["Subarachnoid haemorrhage shows hyperdense blood in the basal cisterns. Sulcal "
        "effacement accompanies raised intracranial pressure."]
PRIVATE = ["Pneumoperitoneum shows free gas under the diaphragm on an erect radiograph. The "
           "Rigler sign outlines both sides of the bowel wall."]
STOP = frozenset({"what", "is", "the", "of", "and", "in", "on", "a", "an", "does", "how",
                  "why", "which", "are", "to", "for", "with"})
WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


class Corpus:
    """Chunk rows keyed by tenant and uploader; logs every retrieval call."""

    def __init__(self, caller: Callable[[], Principal]) -> None:
        self.caller, self.rows, self.retrievals = caller, [], []

    def add(self, who: Principal, title: str, texts: list[str]) -> UUID:
        source = uuid4()
        for n, body in enumerate(texts, start=1):
            self.rows.append({
                "tenant_id": who.tenant_id, "uploaded_by": who.user_id, "id": uuid4(),
                "source_id": source, "source_title": title, "page_from": n, "page_to": n,
                "heading": title, "text": body, "block_refs": [{"page": n, "block": 0}]})
        return source

    def visible(self, user_id: UUID) -> list[dict[str, Any]]:
        tenant = self.caller().tenant_id  # RLS: the session's tenant
        return [r for r in self.rows if r["tenant_id"] == tenant and r["uploaded_by"] == user_id]

    async def lexical(self, _s: Any, user_id: UUID, query: str) -> list[dict[str, Any]]:
        terms = {t.strip() for t in query.split(" or ")} - STOP - {""}
        self.retrievals.append((user_id, query))
        scored = [(len(terms & words(r["text"])), r["id"]) for r in self.visible(user_id)]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
        return [{"id": rid, "score": float(score)} for score, rid in ranked[: search.CANDIDATES]]

    async def dense(self, _s: Any, _u: UUID, _v: Any) -> list[dict[str, Any]]:
        return []  # the tutor env disables query vectors; lexical carries retrieval

    async def hydrate(self, _s: Any, ids: Any) -> dict[UUID, dict[str, Any]]:
        tenant = self.caller().tenant_id
        keep = ("id", "source_id", "source_title", "page_from", "page_to", "heading", "text",
                "block_refs")
        return {r["id"]: {k: r[k] for k in keep} for r in self.rows
                if r["id"] in set(ids) and r["tenant_id"] == tenant}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(search, "hybrid_search", REAL_HYBRID_SEARCH)
        monkeypatch.setattr(search, "lexical", self.lexical)
        monkeypatch.setattr(search, "dense", self.dense)
        monkeypatch.setattr(search, "hydrate", self.hydrate)

    def row(self, chunk_id: str) -> dict[str, Any] | None:
        return next((r for r in self.rows if str(r["id"]) == chunk_id), None)


EXCERPT = re.compile(r'<excerpt id="(S\d+)"[^>]*>\n(.*?)\n</excerpt>', re.S)
FIGURE = re.compile(r'<figure id="(F\d+)"[^>]*>\n(.*?)\n</figure>', re.S)
ITEM = re.compile(r'<item id="(\w+)" kind="[^"]*">\n(.*?)\n</item>', re.S)
SEGMENT = re.compile(r'<segment n="(\d+)" cites="([^"]*)">(.*?)</segment>', re.S)


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".")


def first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".") + "."


def lexical_verdicts(prompt: str) -> dict[str, Any]:
    """Supported only when the segment's text is literally in the evidence it cites."""
    evidence = {label: _norm(body) for label, body in ITEM.findall(prompt)}
    verdicts = []
    for number, cites, text in SEGMENT.findall(prompt):
        cited = " ".join(evidence.get(label, "") for label in cites.split())
        verdict = "supported" if _norm(text) in cited else "unsupported"
        verdicts.append({"segment": int(number), "verdict": verdict, "reason": "Lexical check."})
    return {"verdicts": verdicts}


class EvidenceTransport(FakeTransport):
    """Tutor fake that can only restate the excerpts it was shown."""

    def __init__(self) -> None:
        super().__init__({"coverage": "none", "segments": []})
        self.extra: list[dict[str, Any]] = []
        self.web: dict[str, Any] = {"segments": [], "pages": []}
        self.prompts: list[str] = []

    def compose(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        shown = EXCERPT.findall(prompt)
        segments = [{"text": first_sentence(body), "sources": [label]} for label, body in shown]
        segments += self.extra
        return {"coverage": "full" if segments else "none", "segments": segments}

    def _output(self, call: ModelCall) -> dict[str, Any]:
        base = super()._output(call)  # asserts no open transaction; raises configured errors
        agent = agent_of(call)
        if agent == "tutor":
            return self.web if "WebSearch" in call.tools else self.compose(call.user_prompt)
        if agent == "judge":
            return lexical_verdicts(call.user_prompt)
        return base

    @property
    def tutor_calls(self) -> list[ModelCall]:
        return [c for c in self.calls if agent_of(c) == "tutor" and "WebSearch" not in c.tools]


def figure_hit(who: Principal, description: str, page: int = 5) -> dict[str, Any]:
    return {"id": uuid4(), "source_id": uuid4(), "source_title": f"Plates {who.tenant_id}",
            "page_no": page, "figure_no": 1, "caption": "Synthetic plate", "modality": "XR",
            "anatomy": "chest", "image_key": f"tenants/{who.tenant_id}/figures/x.png",
            "score": 0.5, "description": description}
