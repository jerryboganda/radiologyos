"""In-memory knowledge database for the M2 gate (no PostgreSQL, no model).

``KnowledgeDB`` holds the knowledge tables as dicts. ``FakeSession`` is bound to
one tenant (the RLS model: a session sees only its tenant's rows) and answers
exactly the SQL statements the durable code issues (``apps/worker/app/
knowledge/{db,graph}.py``, ``apps/api/app/knowledge/{service,mappings,
curriculum_review}.py``, and the library ``audit``). An unmodelled statement
fails loudly, so SQL drift in production code shows up here instead of being
silently faked. The row-level proof against real RLS stays in
``test_knowledge_live.py`` and ``test_knowledge_pipeline_live.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from packages.knowledge.text import trigram_similarity

NOW = datetime(2026, 9, 26, tzinfo=UTC)
Params = dict[str, Any]


class Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None, scalar: Any = None) -> None:
        self.rows, self.value = rows or [], scalar

    def mappings(self) -> _Rows:
        return _Rows(self.rows)

    def scalar_one(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value


class _Rows(list[dict[str, Any]]):
    def all(self) -> list[dict[str, Any]]:
        return list(self)

    def first(self) -> dict[str, Any] | None:
        return self[0] if self else None


class KnowledgeDB:
    """Knowledge tables keyed by id; every row carries its ``tenant_id``."""

    def __init__(self) -> None:
        self.sources: dict[UUID, dict[str, Any]] = {}
        self.chunks: list[dict[str, Any]] = []
        self.blocks: list[dict[str, Any]] = []
        self.runs: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.concepts: dict[UUID, dict[str, Any]] = {}
        self.claims: dict[UUID, dict[str, Any]] = {}
        self.conflicts: dict[UUID, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.mappings: dict[UUID, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []

    def session(self, tenant_id: UUID) -> FakeSession:
        return FakeSession(self, tenant_id)

    def add_source(self, tenant: UUID, user: UUID, title: str, texts: list[str]) -> UUID:
        """One chunk and one parsed block per text, on page n (1-based)."""
        source = uuid4()
        self.sources[source] = {"id": source, "tenant_id": tenant, "uploaded_by": user,
                                "title": title, "deleted_at": None, "job_id": uuid4(),
                                "knowledge_step": None}  # its ingest job, pipeline v1
        for n, body in enumerate(texts):
            self.chunks.append({"tenant_id": tenant, "id": uuid4(), "source_id": source,
                                "chunk_no": n, "page_from": n + 1, "page_to": n + 1,
                                "heading": "", "text": body, "block_refs": []})
            self.blocks.append({"tenant_id": tenant, "source_id": source, "page_no": n + 1,
                                "block_no": 0, "text": body, "bbox": [0.1, 0.1, 0.9, 0.9]})
        return source

    def rows(self, table: str, tenant: UUID) -> list[dict[str, Any]]:
        found = getattr(self, table)
        values = found.values() if isinstance(found, dict) else found
        return [row for row in values if row["tenant_id"] == tenant]

    def owned_by(self, source_id: Any, user: UUID) -> bool:
        source = self.sources.get(source_id)
        return bool(source and source["uploaded_by"] == user and source["deleted_at"] is None)


class FakeSession:
    """One tenant's view of ``KnowledgeDB`` that interprets the durable SQL."""

    def __init__(self, db: KnowledgeDB, tenant: UUID) -> None:
        self.db, self.tenant, self.events = db, tenant, []

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.db.rows(table, self.tenant)

    async def execute(self, statement: Any, params: Params | None = None) -> Result:
        sql = " ".join(str(statement).split())
        for needle, handler in HANDLERS:
            if needle in sql:
                self.events.append(needle)
                return handler(self, params or {})
        raise AssertionError(f"unmodelled SQL in the M2 fake: {sql[:90]}")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


# ---------------------------------------------------------------- worker reads/runs


def _chunks(s: FakeSession, p: Params) -> Result:
    rows = sorted((r for r in s.rows("chunks") if r["source_id"] == p["s"]),
                  key=lambda r: r["chunk_no"])
    return Result(rows)


def _blocks(s: FakeSession, p: Params) -> Result:
    return Result([r for r in s.rows("blocks")
                   if r["source_id"] == p["s"] and p["a"] <= r["page_no"] <= p["b"]])


def _run_key(s: FakeSession, p: Params) -> tuple[Any, ...]:
    return (s.tenant, p["s"], p["u"], p["a"], p["v"])


def _run_status(s: FakeSession, p: Params) -> Result:
    run = s.db.runs.get(_run_key(s, p))
    return Result(scalar=run["status"] if run else None)


def _record_run(s: FakeSession, p: Params) -> Result:
    s.db.runs[_run_key(s, p)] = {"tenant_id": s.tenant, "status": p["status"],
                                 "output_ref": p["out"]}
    return Result()


# ---------------------------------------------------------------- graph writes


def _candidates(s: FakeSession, p: Params) -> Result:
    keys = set(p["keys"])
    hits = [r for r in s.rows("concepts")
            if r["normalized_name"] in keys or keys & set(r["alias_keys"])
            or trigram_similarity(r["normalized_name"], p["key"]) >= p["floor"]]
    hits.sort(key=lambda r: trigram_similarity(r["normalized_name"], p["key"]), reverse=True)
    return Result(hits[:8])


def _update_aliases(s: FakeSession, p: Params) -> Result:
    s.db.concepts[p["id"]].update(aliases=list(p["a"]), alias_keys=list(p["k"]))
    return Result()


def _insert_concept(s: FakeSession, p: Params) -> Result:
    for row in s.rows("concepts"):
        if row["normalized_name"] == p["key"]:  # ON CONFLICT (tenant_id, normalized_name)
            return Result(scalar=row["id"])
    new = uuid4()
    s.db.concepts[new] = {"id": new, "tenant_id": s.tenant, "name": p["name"],
                          "normalized_name": p["key"], "concept_type": p["type"],
                          "aliases": list(p["aliases"]), "alias_keys": list(p["keys"]),
                          "curriculum_code": None, "curriculum_confidence": None}
    return Result(scalar=new)


def _same_concept_claims(s: FakeSession, p: Params) -> Result:
    return Result([r for r in s.rows("claims") if r["concept_id"] == p["c"]
                   and r["status"] in ("active", "disputed")])


def _add_support(s: FakeSession, p: Params) -> Result:
    claim = s.db.claims[p["id"]]
    claim["supporting"] = [*claim["supporting"], *json.loads(p["c"])]
    claim["verification"] = "verified"
    return Result()


def _insert_claim(s: FakeSession, p: Params) -> Result:
    new = uuid4()
    s.db.claims[new] = {
        "id": new, "tenant_id": s.tenant, "concept_id": p["c"], "claim_type": p["type"],
        "statement": p["statement"], "evidence_span": p["span"], "source_id": p["s"],
        "chunk_id": p["chunk"], "page_from": p["pf"], "page_to": p["pt"],
        "citation": json.loads(p["citation"]), "importance": p["importance"],
        "modality": p["modality"], "agent_version": p["agent"], "status": "active",
        "verification": "unverified", "supporting": [],
    }
    return Result(scalar=new)


def _insert_conflict(s: FakeSession, p: Params) -> Result:
    if any((r["claim_a"], r["claim_b"]) == (p["a"], p["b"]) for r in s.rows("conflicts")):
        return Result()  # UNIQUE (tenant_id, claim_a, claim_b) ... DO NOTHING
    new = uuid4()
    s.db.conflicts[new] = {"id": new, "tenant_id": s.tenant, "concept_id": p["c"],
                           "claim_a": p["a"], "claim_b": p["b"], "kind": p["k"],
                           "description": p["d"], "status": "open", "resolution": None,
                           "preferred_claim": None, "resolved_by": None,
                           "resolved_at": None, "created_at": NOW}
    return Result()


def _dispute(s: FakeSession, p: Params) -> Result:
    for claim_id in (p["a"], p["b"]):
        s.db.claims[claim_id]["status"] = "disputed"
    return Result()


def _insert_edge(s: FakeSession, p: Params) -> Result:
    key = (p["a"], p["b"], p["r"])
    if not any((e["from_concept"], e["to_concept"], e["relation"]) == key
               for e in s.rows("edges")):
        s.db.edges.append({"tenant_id": s.tenant, "from_concept": p["a"], "to_concept": p["b"],
                           "relation": p["r"], "source_id": p["s"],
                           "citation": json.loads(p["c"])})
    return Result()


def _upsert_mapping(s: FakeSession, p: Params) -> Result:
    key = (p["s"], p["u"], p["code"], p["topic"])
    for row in s.rows("mappings"):
        if (row["source_id"], row["unit_hash"], row["curriculum_code"], row["topic"]) == key:
            row.update(confidence=p["conf"], status=p["status"], chunk_id=p["chunk"],
                       curriculum_node_id=p["node"])
            return Result()
    new = uuid4()
    s.db.mappings[new] = {"id": new, "tenant_id": s.tenant, "source_id": p["s"],
                          "unit_hash": p["u"], "chunk_id": p["chunk"], "page_from": p["pf"],
                          "page_to": p["pt"], "curriculum_code": p["code"],
                          "curriculum_node_id": p["node"], "topic": p["topic"],
                          "confidence": p["conf"], "status": p["status"],
                          "agent_version": p["agent"], "created_at": NOW}
    return Result()


def _map_concepts(s: FakeSession, p: Params) -> Result:
    for concept_id in p["ids"]:
        row = s.db.concepts[concept_id]
        if row["curriculum_code"] is None or (row["curriculum_confidence"] or 0) < p["conf"]:
            row.update(curriculum_code=p["code"], curriculum_confidence=p["conf"])
    return Result()


# ---------------------------------------------------------------- API reads/writes


def _side(claim: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {f"{prefix}_id": claim["id"], f"{prefix}_statement": claim["statement"],
            f"{prefix}_span": claim["evidence_span"], f"{prefix}_citation": claim["citation"]}


def _list_conflicts(s: FakeSession, p: Params) -> Result:
    out = []
    for row in s.rows("conflicts"):
        a, b = s.db.claims[row["claim_a"]], s.db.claims[row["claim_b"]]
        if not s.db.owned_by(a["source_id"], p["u"]):  # WHERE sa.uploaded_by = :u
            continue
        if p["status"] is not None and row["status"] != p["status"]:
            continue
        if p["concept"] is not None and row["concept_id"] != p["concept"]:
            continue
        fields = {k: row[k] for k in ("id", "concept_id", "kind", "description", "status",
                                      "resolution", "preferred_claim", "resolved_at",
                                      "created_at")}
        out.append({**fields, "concept_name": s.db.concepts[row["concept_id"]]["name"],
                    **_side(a, "a"), **_side(b, "b")})
    return Result(out)


def _resolve(s: FakeSession, p: Params) -> Result:
    s.db.conflicts[p["id"]].update(status="resolved", resolution=p["r"],
                                   preferred_claim=p["p"], resolved_by=p["u"],
                                   resolved_at=NOW)
    return Result()


def _settle_claim(s: FakeSession, p: Params) -> Result:
    still_open = any(r["status"] == "open" and p["id"] in (r["claim_a"], r["claim_b"])
                     for r in s.rows("conflicts"))
    if not still_open:
        s.db.claims[p["id"]]["status"] = p["s"]
    return Result()


def _audit(s: FakeSession, p: Params) -> Result:
    s.db.audit.append({"tenant_id": p["t"], "actor": p["u"], "action": p["a"],
                       "target_type": p["tt"], "target_id": p["tid"],
                       "metadata": json.loads(p["m"])})
    return Result()


def _search_concepts(s: FakeSession, p: Params) -> Result:
    key, out = p["key"], []
    for row in s.rows("concepts"):
        claims = [c for c in s.rows("claims") if c["concept_id"] == row["id"]]
        if not any(s.db.owned_by(c["source_id"], p["u"]) for c in claims):
            continue
        if key and not (key in row["normalized_name"] or key in row["alias_keys"]
                        or trigram_similarity(row["normalized_name"], key) >= 0.4):
            continue
        opened = [x for x in s.rows("conflicts")
                  if x["concept_id"] == row["id"] and x["status"] == "open"]
        out.append({k: row[k] for k in ("id", "name", "aliases", "concept_type",
                                        "curriculum_code")}
                   | {"claim_count": len(claims), "open_conflicts": len(opened)})
    return Result(out[: p["limit"]])


def _select_mappings(s: FakeSession, p: Params) -> Result:
    out = []
    for row in s.rows("mappings"):
        if not s.db.owned_by(row["source_id"], p["u"]):
            continue
        if row["id"] != p.get("id", row["id"]) or row["status"] != p.get("status", row["status"]):
            continue
        chunk = next((c for c in s.rows("chunks") if c["id"] == row["chunk_id"]), None)
        hidden = ("tenant_id", "unit_hash", "chunk_id")
        out.append({k: v for k, v in row.items() if k not in hidden}
                   | {"source_title": s.db.sources[row["source_id"]]["title"],
                      "excerpt": (chunk["text"] if chunk else "")[:400]})
    return Result(out)


def _ingest_job(s: FakeSession, p: Params) -> Result:
    source = s.db.sources.get(p["s"])
    if source is None or source["tenant_id"] != s.tenant or not s.db.owned_by(p["s"], p["u"]):
        return Result()
    return Result([{"id": source["job_id"], "tenant_id": s.tenant, "entity_id": p["s"],
                    "pipeline_version": 1}])


def _pending_step(s: FakeSession, p: Params) -> Result:
    s.db.sources[p["e"]]["knowledge_step"] = "pending"
    return Result()


def _set_mapping_status(s: FakeSession, p: Params) -> Result:
    s.db.mappings[p["id"]]["status"] = p["s"]
    return Result()


def _insert_review(s: FakeSession, p: Params) -> Result:
    s.db.reviews.append({"id": uuid4(), "tenant_id": s.tenant, "pack_id": p["p"],
                         "pack_version": p["v"], "content_hash": p["h"], "decision": p["d"],
                         "notes": p["n"], "decided_at": NOW})
    return Result()


def _reviews(s: FakeSession, p: Params) -> Result:
    return Result([{k: v for k, v in r.items() if k != "tenant_id"}
                   for r in reversed(s.rows("reviews")) if r["pack_id"] == p["p"]][: p["n"]])


HANDLERS: list[tuple[str, Callable[[FakeSession, Params], Result]]] = [
    ("FROM chunks WHERE source_id = :s ORDER BY chunk_no", _chunks),
    ("FROM source_blocks WHERE source_id = :s", _blocks),
    ("SELECT status FROM knowledge_runs", _run_status),
    ("INSERT INTO knowledge_runs", _record_run),
    ("FROM concepts WHERE normalized_name = ANY", _candidates),
    ("UPDATE concepts SET aliases", _update_aliases),
    ("INSERT INTO concepts (", _insert_concept),
    ("SELECT id, statement, source_id FROM claims", _same_concept_claims),
    ("UPDATE claims SET supporting", _add_support),
    ("INSERT INTO claims (", _insert_claim),
    ("INSERT INTO knowledge_conflicts", _insert_conflict),
    ("UPDATE claims SET status = 'disputed'", _dispute),
    ("INSERT INTO concept_edges", _insert_edge),
    ("INSERT INTO curriculum_mappings", _upsert_mapping),
    ("UPDATE concepts SET curriculum_code", _map_concepts),
    ("FROM knowledge_conflicts x JOIN concepts k", _list_conflicts),
    ("UPDATE knowledge_conflicts SET status = 'resolved'", _resolve),
    ("UPDATE claims SET status = :s WHERE id = :id AND NOT EXISTS", _settle_claim),
    ("INSERT INTO audit_log", _audit),
    ("FROM concepts k WHERE EXISTS", _search_concepts),
    ("FROM curriculum_mappings m JOIN sources s", _select_mappings),
    ("UPDATE curriculum_mappings SET status = :s WHERE id = :id", _set_mapping_status),
    ("INSERT INTO curriculum_reviews", _insert_review),
    ("FROM jobs j JOIN sources s ON s.id = j.entity_id", _ingest_job),
    ("INSERT INTO job_steps", _pending_step),
    ("FROM curriculum_reviews WHERE pack_id", _reviews),
]
