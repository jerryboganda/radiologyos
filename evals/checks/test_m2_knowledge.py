"""M2 eval gate: cited extraction, entity resolution, explicit conflicts, editor authority.

Runs the durable notes worker (``apps/worker/app/knowledge``), ``packages/knowledge``,
and the ``/v1/knowledge`` routers against an in-memory, tenant-bound SQL fake
(``_m2_support``) and a scripted model transport. It proves:

  I  only claims whose evidence span is verbatim in the chunk are kept, each cited to
     source/page/block/bbox; short chunks are skipped; units are idempotent per (text
     hash, agent version, PIPELINE_VERSION) in ``knowledge_runs``; a model failure
     stores no claims and a usage limit defers;
  J  concepts resolve by alias/normalised key without duplicates, per tenant;
  K  a contradiction is an explicit open conflict, both claims ``disputed``, neither
     overwritten; agreement is supporting evidence; mappings keep known codes and
     queue confidence < 0.7 for review;
  L  over HTTP, extraction requests and the conflict/mapping queues are owner scoped,
     resolution is audited by id only, unknown/foreign conflicts are 404, bodies are
     closed (422), and approving the curriculum needs a privileged role (403).

The fake models RLS as "a session sees only its tenant's rows"; the row-level proof as
the runtime role is ``test_knowledge_live.py`` / ``test_knowledge_pipeline_live.py`` (CI).
All content is synthetic.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.api import curriculum as curriculum_api
from apps.api.app.api import knowledge as knowledge_api
from apps.api.app.main import app
from apps.api.app.security.context import local_principal
from apps.api.app.security.principal import Principal
from apps.worker.app.knowledge import notes
from apps.worker.app.knowledge.runtime import Deferred, KnowledgeDeps
from evals.checks._knowledge_support import ScriptedTransport
from evals.checks._m2_support import KnowledgeDB
from fastapi import HTTPException
from fastapi.testclient import TestClient
from packages.curriculum.loader import radiology_hash
from packages.knowledge.text import collapse_ws
from packages.models.claude_code import ModelCallError, UsageLimitError

TENANT_A = UUID("30000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("30000000-0000-4000-8000-00000000000b")
USER_A = UUID("10000000-0000-4000-8000-00000000000a")
USER_A2 = UUID("10000000-0000-4000-8000-0000000000a2")
USER_B = UUID("10000000-0000-4000-8000-00000000000b")
VERSION = 7
CHUNK_60 = (
    "Synthetic chest notes. Usual interstitial pneumonia (UIP) shows basal subpleural "
    "reticulation with honeycombing and traction bronchiectasis on HRCT. In this synthetic "
    "teaching note the typical age at presentation is over 60 years and men are affected "
    "more often than women.")
CHUNK_50 = (
    "Second synthetic paragraph. For UIP the typical age at presentation is over 50 years "
    "according to this contradictory synthetic note, which exists only to exercise the "
    "conflict detector of the knowledge pipeline in automated tests.")
CHUNK_AGREE = (
    "Third synthetic paragraph, from another synthetic deck. It repeats that the typical age at "
    "presentation is over 60 years for usual interstitial pneumonia so that the pipeline "
    "records a second supporting citation instead of a duplicate claim.")
CHUNK_HEAD = (
    "Synthetic neuro notes. Subarachnoid haemorrhage shows hyperdense blood in the basal "
    "cisterns with sulcal effacement on non-contrast CT; honeycombing is a lung sign and is "
    "mentioned here only so the same concept name exists in a second tenant.")
SHORT = "Too short to extract."
INVENTED = "an invented span that is not in the chunk"
UIP = "Usual interstitial pneumonia"
AGE = "Typical age at presentation of UIP is over {} years"
SPAN = "typical age at presentation is over {} years"


def _claim(concept: str, text: str, span: str) -> dict[str, Any]:
    return {"concept": concept, "type": "epidemiology", "text": text, "evidence_span": span,
            "importance": 4, "modality": "", "source_doubt": ""}


def _concept(name: str, kind: str, *aliases: str) -> dict[str, Any]:
    return {"name": name, "type": kind, "aliases": list(aliases)}


def _extract(prompt: str) -> dict[str, Any]:
    span, out = SPAN, {"concepts": [], "claims": [], "relations": []}
    if "Second synthetic" in prompt:
        return out | {"concepts": [_concept("UIP", "disease")],
                      "claims": [_claim("UIP", AGE.format(50), span.format(50))]}
    if "Third synthetic" in prompt:
        return out | {"claims": [_claim(UIP, AGE.format(60), span.format(60))]}
    if "Synthetic neuro" in prompt:
        return out | {"concepts": [_concept("Honeycombing", "sign")], "claims": [_claim(
            "Subarachnoid haemorrhage", "SAH causes sulcal effacement",
            "sulcal effacement on non-contrast CT")]}
    return {"concepts": [_concept(UIP, "disease", "UIP"), _concept("Honeycombing", "sign")],
            "claims": [_claim(UIP, AGE.format(60), span.format(60)),
                       _claim(UIP, "UIP is most common in children", INVENTED)],
            "relations": [{"src": "Honeycombing", "dst": UIP, "relation": "sign_of"}]}


def _classify(prompt: str) -> dict[str, Any]:
    codes = (("CHEST", "usual interstitial pneumonia", 0.9), ("PHYSICS", "hrct technique", 0.4),
             ("NOT_A_CODE", "x", 0.99))
    return {"topics": [{"curriculum_code": c, "topic": t, "confidence": n} for c, t, n in codes]}


def transport() -> ScriptedTransport:
    return ScriptedTransport({"knowledge_extract": _extract, "topic_classify": _classify})


def extract(db: KnowledgeDB, tenant: UUID, source: UUID, model: Any, version: int = VERSION) -> str:
    deps = KnowledgeDeps(engine=None, transport=model)  # type: ignore[arg-type]
    row = {"id": source, "title": db.sources[source]["title"]}
    return asyncio.run(notes.run_notes(deps, tenant, row, version))


class World:
    def __init__(self) -> None:
        self.db, self.model = KnowledgeDB(), transport()
        self.sa = self.db.add_source(TENANT_A, USER_A, "Chest", [CHUNK_60, CHUNK_50, SHORT])
        self.sb = self.db.add_source(TENANT_B, USER_B, "Neuro", [CHUNK_HEAD])
        self.escalated: list[tuple[Any, ...]] = []

    def run_all(self) -> World:
        extract(self.db, TENANT_A, self.sa, self.model)
        extract(self.db, TENANT_B, self.sb, self.model)
        return self

    def claims(self, tenant: UUID = TENANT_A) -> list[dict[str, Any]]:
        return self.db.rows("claims", tenant)

    def concepts(self, tenant: UUID = TENANT_A) -> dict[str, dict[str, Any]]:
        return {c["normalized_name"]: c for c in self.db.rows("concepts", tenant)}


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    built = World()

    @asynccontextmanager
    async def tenant_tx(_engine: Any, tenant_id: UUID) -> AsyncIterator[Any]:
        yield built.db.session(tenant_id)

    async def escalate(*args: Any) -> None:  # collect & ask is proven in its live test
        built.escalated.append(args[3:])

    monkeypatch.setattr(notes, "tenant_tx", tenant_tx)
    monkeypatch.setattr(notes.escalations, "escalate", escalate)
    return built


# ---------------------------------------------------------------- slice I


def test_only_claims_with_verbatim_evidence_are_kept(world: World) -> None:
    claims = world.run_all().claims()
    assert len(claims) == 2 and all(c["evidence_span"] != INVENTED for c in claims)
    for claim in claims:
        chunk = next(c for c in world.db.chunks if c["id"] == claim["chunk_id"])
        assert collapse_ws(claim["evidence_span"]) in collapse_ws(chunk["text"])
    refs = {r["output_ref"] for r in world.db.rows("runs", TENANT_A)}
    assert "claims:1,rej:1" in refs  # the invented span was counted, never stored


def test_every_kept_claim_is_cited_to_source_page_and_block(world: World) -> None:
    for claim in world.run_all().claims():
        citation = claim["citation"]
        assert citation["source_id"] == str(world.sa) and citation["source_title"] == "Chest"
        assert citation["chunk_id"] == str(claim["chunk_id"])
        assert citation["page_from"] >= 1 and citation["blocks"]
        for block in citation["blocks"]:
            assert citation["page_from"] <= block["page_no"] <= citation["page_to"]
            assert block["block_no"] >= 0 and len(block["bbox"]) == 4


def test_reruns_skip_done_units_and_a_new_version_never_duplicates(world: World) -> None:
    world.run_all()
    assert world.model.calls.count("knowledge_extract") == 3  # 2 in A (short skipped), 1 in B
    before = (len(world.claims()), len(world.concepts()), len(world.db.conflicts))
    extract(world.db, TENANT_A, world.sa, world.model)
    assert world.model.calls.count("knowledge_extract") == 3  # knowledge_runs: nothing redone
    assert (len(world.claims()), len(world.concepts()), len(world.db.conflicts)) == before
    keys = {key[2:] for key in world.db.runs if key[0] == TENANT_A}
    assert {(agent, version) for _, agent, version in keys} == {(notes.EXTRACT, VERSION)}
    assert all(unit.startswith("chunk:") and len(unit) == 38 for unit, _, _ in keys)
    extract(world.db, TENANT_A, world.sa, world.model, VERSION + 1)  # new PIPELINE_VERSION
    assert world.model.calls.count("knowledge_extract") == 5
    assert (len(world.claims()), len(world.concepts()), len(world.db.conflicts)) == before


@pytest.mark.parametrize("error", [None, ModelCallError("x"), UsageLimitError("limit")])
def test_a_model_failure_never_stores_fake_claims(world: World, error: Any) -> None:
    model = failing(error) if error else None
    if isinstance(error, UsageLimitError):  # deferred: no unit is marked done, so it resumes
        with pytest.raises(Deferred):
            extract(world.db, TENANT_A, world.sa, model)
        assert world.db.runs == {}
    else:
        extract(world.db, TENANT_A, world.sa, model)
        assert {r["status"] for r in world.db.rows("runs", TENANT_A)} == {"failed"}
        if error is not None:  # Luna and Sol both failed: saved for the owner's approval
            assert world.escalated and all(e[0] == "knowledge_extract" for e in world.escalated)
    assert world.claims() == [] and world.concepts() == {}


def failing(exc: Exception) -> ScriptedTransport:
    def script(_prompt: str) -> dict[str, Any]:
        raise exc
    return ScriptedTransport({"knowledge_extract": script, "topic_classify": script})


# ---------------------------------------------------------------- slice J


def test_alias_resolution_never_duplicates_a_concept(world: World) -> None:
    concepts = world.run_all().concepts()
    assert set(concepts) == {"usual interstitial pneumonia", "honeycombing"}  # "UIP" merged
    uip = concepts[UIP.lower()]
    assert "UIP" in uip["aliases"] and "usual interstitial pneumonia" in uip["alias_keys"]
    assert {c["concept_id"] for c in world.claims()} == {uip["id"]}
    assert len(world.db.edges) == 1 and world.db.edges[0]["relation"] == "sign_of"


def test_the_same_name_in_another_tenant_is_a_separate_concept(world: World) -> None:
    a, b = world.run_all().concepts(), world.concepts(TENANT_B)
    assert a["honeycombing"]["id"] != b["honeycombing"]["id"] and b["honeycombing"][
        "tenant_id"] == TENANT_B
    assert {c["source_id"] for c in world.claims(TENANT_B)} == {world.sb}
    assert "usual interstitial pneumonia" not in b and "subarachnoid hemorrhage" not in a


# ---------------------------------------------------------------- slice K


def test_a_contradiction_is_explicit_open_and_overwrites_nothing(world: World) -> None:
    [conflict] = world.run_all().db.rows("conflicts", TENANT_A)
    assert (conflict["kind"], conflict["status"]) == ("numeric", "open")
    assert "years" in conflict["description"]
    assert {c["id"] for c in world.claims()} == {conflict["claim_a"], conflict["claim_b"]}
    assert {c["status"] for c in world.claims()} == {"disputed"}
    assert {c["statement"] for c in world.claims()} == {AGE.format(60), AGE.format(50)}
    assert world.db.rows("conflicts", TENANT_B) == []


def test_agreement_from_a_second_source_is_support_not_a_new_claim(world: World) -> None:
    world.run_all()
    second = world.db.add_source(TENANT_A, USER_A, "Second deck", [CHUNK_AGREE])
    extract(world.db, TENANT_A, second, world.model)
    assert len(world.claims()) == 2
    sixty = next(c for c in world.claims() if "60" in c["statement"])
    assert sixty["verification"] == "verified"
    assert [s["source_id"] for s in sixty["supporting"]] == [str(second)]


def test_curriculum_mapping_keeps_known_codes_and_queues_low_confidence(world: World) -> None:
    mappings = world.run_all().db.rows("mappings", TENANT_A)
    assert {(m["curriculum_code"], m["status"]) for m in mappings} == {
        ("CHEST", "accepted"), ("PHYSICS", "review")}
    assert all(m["curriculum_node_id"] == m["curriculum_code"] for m in mappings)
    assert world.concepts()["usual interstitial pneumonia"]["curriculum_code"] == "CHEST"
    for mapping in mappings:  # coverage is traceable to a cited chunk of the source
        chunk = next(c for c in world.db.chunks if c["id"] == mapping["chunk_id"])
        assert chunk["source_id"] == mapping["source_id"] == world.sa


# ---------------------------------------------------------------- slice L (HTTP)

OTHERS = (Principal(USER_A2, TENANT_A, "editor"), Principal(USER_B, TENANT_B, "superadmin"))


@pytest.fixture()
def http(world: World) -> Iterator[tuple[TestClient, World, dict[str, Principal]]]:
    world.run_all()
    who = {"p": Principal(USER_A, TENANT_A)}
    for router in (knowledge_api, curriculum_api):
        app.dependency_overrides[router.principal_context] = lambda: who["p"]
        app.dependency_overrides[router.tenant_db_session] = (
            lambda: world.db.session(who["p"].tenant_id))
    try:
        yield TestClient(app), world, who
    finally:
        app.dependency_overrides.clear()


def test_only_the_owner_can_request_extraction(http: Any, monkeypatch: Any) -> None:
    client, world, who = http
    queued: list[Any] = []
    monkeypatch.setattr(knowledge_api, "enqueue_knowledge", lambda *args: queued.append(args))
    target = f"/v1/knowledge/sources/{world.sa}/extract"
    for other in OTHERS:
        who["p"] = other
        assert client.post(target).status_code == 404
    who["p"] = Principal(USER_A, TENANT_A)
    assert client.post(target, json={"mode": "everything"}).status_code == 422
    assert client.post(target, json={"mode": "notes"}).status_code == 202
    assert [args[:2] for args in queued] == [(TENANT_A, world.sa)]
    assert world.db.sources[world.sa]["knowledge_step"] == "pending"
    assert [a["action"] for a in world.db.audit] == ["knowledge.extract_requested"]


def _conflict_id(world: World) -> UUID:
    return UUID(str(world.db.rows("conflicts", TENANT_A)[0]["id"]))


def test_the_conflict_queue_is_owner_scoped(http: Any) -> None:
    client, world, who = http
    [row] = client.get("/v1/knowledge/conflicts").json()
    assert row["status"] == "open" and row["kind"] == "numeric"
    for side in ("claim_a", "claim_b"):
        assert row[side]["citation"]["source_id"] == str(world.sa)
    for other in OTHERS:
        who["p"] = other  # another member of the tenant, or another tenant entirely
        assert client.get("/v1/knowledge/conflicts").json() == []


def test_resolution_is_audited_by_id_and_keeps_both_claims(http: Any) -> None:
    client, world, _ = http
    conflict = world.db.conflicts[_conflict_id(world)]
    keep = conflict["claim_a"]
    response = client.post(f"/v1/knowledge/conflicts/{conflict['id']}/resolve", json={
        "resolution": "Prefer the textbook value", "preferred_claim_id": str(keep)})
    assert response.status_code == 200 and response.json()["status"] == "resolved"
    assert conflict["status"] == "resolved" and conflict["resolved_by"] == USER_A
    statuses = {c["id"]: c["status"] for c in world.claims()}
    assert statuses == {keep: "active", conflict["claim_b"]: "superseded"}  # nothing deleted
    [entry] = world.db.audit
    assert entry["action"] == "knowledge.conflict_resolved"
    assert entry["target_id"] == str(conflict["id"])
    assert entry["metadata"] == {"preferred_claim": str(keep)}  # ids only, no claim text


def test_foreign_or_unknown_conflicts_are_404(http: Any) -> None:
    client, world, who = http
    target = f"/v1/knowledge/conflicts/{_conflict_id(world)}/resolve"
    for other in OTHERS:
        who["p"] = other
        assert client.post(target, json={"resolution": "keep both"}).status_code == 404
    who["p"] = Principal(USER_A, TENANT_A)
    missing = "/v1/knowledge/conflicts/40000000-0000-4000-8000-0000000000ff/resolve"
    assert client.post(missing, json={"resolution": "keep both"}).status_code == 404
    assert world.db.rows("conflicts", TENANT_A)[0]["status"] == "open" and not world.db.audit


@pytest.mark.parametrize("body", [
    {"resolution": ""}, {"resolution": "x" * 2001}, {"resolution": 123}, {},
    {"resolution": "ok", "preferred_claim_id": "not-a-uuid"},
    {"resolution": "ok", "preferred_claim_id": "40000000-0000-4000-8000-0000000000ff"},
    {"resolution": "keep both", "override_rls": True},
])
def test_resolution_accepts_only_the_declared_body(http: Any, body: dict[str, Any]) -> None:
    client, world, _ = http
    response = client.post(f"/v1/knowledge/conflicts/{_conflict_id(world)}/resolve", json=body)
    assert response.status_code == 422
    assert world.db.rows("conflicts", TENANT_A)[0]["status"] == "open" and not world.db.audit


def test_the_mapping_review_queue_is_owner_scoped_and_closed(http: Any) -> None:
    client, world, who = http
    queue = client.get("/v1/knowledge/mappings?status=review").json()
    assert {m["curriculum_code"] for m in queue} == {"PHYSICS"} and queue[0]["excerpt"]
    target = f"/v1/knowledge/mappings/{queue[0]['id']}/decide"
    for decision in ("approve", "delete", "", "ACCEPT"):
        assert client.post(target, json={"decision": decision}).status_code == 422
    who["p"] = Principal(USER_A2, TENANT_A, "editor")
    assert client.get("/v1/knowledge/mappings?status=review").json() == []
    assert client.post(target, json={"decision": "accept"}).status_code == 404
    who["p"] = Principal(USER_A, TENANT_A)
    assert client.post(target, json={"decision": "accept"}).json()["status"] == "accepted"
    assert [a["action"] for a in world.db.audit] == ["knowledge.mapping_decided"]


@pytest.mark.parametrize("role", ["student", "editor"])
def test_approving_the_curriculum_needs_a_privileged_role(http: Any, role: str) -> None:
    client, world, who = http
    who["p"] = Principal(USER_A, TENANT_A, role)
    body = {"decision": "approved", "content_hash": radiology_hash()}
    assert client.post("/v1/knowledge/curriculum/decision", json=body).status_code == 403
    assert world.db.reviews == [] and world.db.audit == []
    who["p"] = Principal(USER_A, TENANT_A, "org_admin")
    approved = client.post("/v1/knowledge/curriculum/decision", json=body)
    assert approved.status_code == 200 and approved.json()["review_status"] == "approved"
    assert [a["action"] for a in world.db.audit] == ["knowledge.curriculum_approved"]


@pytest.mark.parametrize("role", ["learner", "admin", "EDITOR", "super_admin", "root", "", None])
def test_only_declared_roles_are_accepted_and_none_is_unprivileged(role: str | None) -> None:
    if role:  # an unknown role is rejected outright (400), never coerced to a default
        with pytest.raises(HTTPException, match="400: invalid local role"):
            local_principal(str(USER_A), str(TENANT_A), role)
    else:  # an absent or blank role never becomes a privilege grant
        assert local_principal(str(USER_A), str(TENANT_A), role) == Principal(USER_A, TENANT_A)


def test_concept_reads_are_tenant_and_owner_scoped(http: Any) -> None:
    client, _, who = http
    a = {c["name"]: c for c in client.get("/v1/knowledge/concepts").json()}
    assert a["Usual interstitial pneumonia"]["open_conflicts"] == 1
    who["p"] = Principal(USER_B, TENANT_B)
    b = {c["name"]: c for c in client.get("/v1/knowledge/concepts").json()}
    assert "Subarachnoid haemorrhage" in b and "Subarachnoid haemorrhage" not in a and UIP not in b
    assert {c["id"] for c in a.values()}.isdisjoint(c["id"] for c in b.values())
    who["p"] = Principal(USER_A2, TENANT_A)
    assert client.get("/v1/knowledge/concepts").json() == []
