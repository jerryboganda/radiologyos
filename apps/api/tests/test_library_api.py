"""HTTP contract for /v1/library with the real service over an in-memory tenant DB.

Upload, list, detail, and delete run the durable ``library.service`` SQL paths
against a fake session bound to the caller's tenant (RLS emulation); the page
reader and search functions are replaced by owner-scoped fakes, while image
bytes go through the real ``reader.fetch_image`` tenant-prefix check.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.app.api import library
from apps.api.app.core.config import get_settings
from apps.api.app.library import reader, search
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from apps.api.tests.pdf_fixture import make_pdf
from fastapi.testclient import TestClient
from packages.library import storage

TENANT = UUID("20000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("20000000-0000-4000-8000-00000000000b")
OWNER = Principal(UUID("10000000-0000-4000-8000-000000000001"), TENANT)
PEER = Principal(UUID("10000000-0000-4000-8000-000000000002"), TENANT)  # same tenant
STRANGER = Principal(UUID("10000000-0000-4000-8000-000000000003"), TENANT_B)
PDF = make_pdf([["Chest radiography", "A pleural effusion blunts the costophrenic angle."]])
DICOM = b"\x00" * 128 + b"DICM" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\nsynthetic"


class Rows(list[dict[str, Any]]):
    def mappings(self) -> Rows:
        return self

    scalars = mappings

    def first(self) -> dict[str, Any] | None:
        return self[0] if self else None

    def scalar_one(self) -> Any:
        return next(iter(self[0].values()))

    def all(self) -> list[Any]:
        return [next(iter(r.values())) for r in self]


class LibraryDB:
    """The sources a tenant session can see, plus pages and figures for the reader."""

    def __init__(self) -> None:
        self.sources: dict[UUID, dict[str, Any]] = {}
        self.pages: dict[tuple[UUID, int], str] = {}  # (source, page) -> image key
        self.figures: dict[UUID, tuple[UUID, str]] = {}  # figure -> (source, image key)
        self.jobs: list[dict[str, Any]] = []

    def owned(self, user_id: UUID, source_id: UUID) -> dict[str, Any] | None:
        row = self.sources.get(source_id)
        return row if row and row["uploaded_by"] == user_id else None


class TenantSession:
    """Answers the ``library.service`` statements for one tenant only."""

    def __init__(self, db: LibraryDB, tenant_id: UUID) -> None:
        self.db, self.tenant_id = db, tenant_id

    def _visible(self) -> list[dict[str, Any]]:
        return [s for s in self.db.sources.values() if s["tenant_id"] == self.tenant_id]

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Rows:
        sql, p = " ".join(str(statement).split()), params or {}
        if "WHERE sha256 = :h" in sql:
            return Rows([s for s in self._visible() if s["sha256"] == p["h"]])
        if sql.startswith("INSERT INTO sources"):
            assert p["t"] == self.tenant_id
            self.db.sources[p["id"]] = {
                "id": p["id"], "tenant_id": p["t"], "uploaded_by": p["u"], "title": p["title"],
                "kind": p["kind"], "status": "uploaded", "sha256": p["sha"], "byte_size": p["size"],
                "page_count": None, "created_at": datetime.now(UTC), "storage_key": p["key"],
                "legal_hold": False, "pages_parsed": 0, "figure_count": 0}
        elif sql.startswith("INSERT INTO jobs"):
            self.db.jobs.append(dict(p))
        elif "FROM sources s WHERE s.uploaded_by = :u" in sql or "AND uploaded_by = :u" in sql:
            return Rows([s for s in self._visible() if s["uploaded_by"] == p["u"]
                         and p.get("id", s["id"]) == s["id"]])
        elif sql.startswith("SELECT legal_hold"):
            return Rows([{"h": s["legal_hold"]} for s in self._visible() if s["id"] == p["id"]])
        elif sql.startswith("DELETE FROM sources"):
            self.db.sources.pop(p["id"])
        return Rows()

    async def commit(self) -> None:
        return None


class Who:
    principal = OWNER


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    db, store = LibraryDB(), storage.MemoryObjectStore()
    state: dict[str, Any] = {"db": db, "store": store, "enqueued": [], "searched": []}
    Who.principal = OWNER
    app.dependency_overrides[library.principal_context] = lambda: Who.principal
    app.dependency_overrides[library.tenant_db_session] = (
        lambda: TenantSession(db, Who.principal.tenant_id))
    monkeypatch.setattr(library, "get_store", lambda: store)
    monkeypatch.setattr(library, "enqueue_ingest",
                        lambda tenant, job: state["enqueued"].append((tenant, job)))

    async def no_vector(tenant_id: UUID, query: str) -> None:
        return None

    monkeypatch.setattr(library, "query_vector", no_vector)
    _fake_reader(monkeypatch, db)
    _fake_search(monkeypatch, db, state)
    yield state
    app.dependency_overrides.clear()


def _fake_reader(monkeypatch: pytest.MonkeyPatch, db: LibraryDB) -> None:
    async def read_page(session: Any, user: UUID, source: UUID, page: int) -> Any:
        if not db.owned(user, source) or (source, page) not in db.pages:
            return None
        return {"source_id": source, "page_no": page, "blocks": [{"block_no": 0}]}

    async def page_key(session: Any, user: UUID, source: UUID, page: int) -> str | None:
        return db.pages.get((source, page)) if db.owned(user, source) else None

    async def figure_key(session: Any, user: UUID, figure: UUID) -> str | None:
        source, key = db.figures.get(figure, (uuid4(), ""))
        return key if db.owned(user, source) else None

    monkeypatch.setattr(reader, "read_page", read_page)
    monkeypatch.setattr(reader, "image_key_for_page", page_key)
    monkeypatch.setattr(reader, "image_key_for_figure", figure_key)


def _figure_row(db: LibraryDB, figure_id: UUID) -> dict[str, Any]:
    source, key = db.figures[figure_id]
    return {"id": figure_id, "source_id": source, "source_title": "Synthetic", "page_no": 1,
            "caption": "Synthetic CXR", "description": "effusion", "modality": "X-ray",
            "anatomy": "chest", "image_key": key}


def _fake_search(monkeypatch: pytest.MonkeyPatch, db: LibraryDB, state: dict[str, Any]) -> None:
    async def hybrid(session: Any, user: UUID, query: str, vector: Any, limit: int) -> Any:
        state["searched"].append((user, query, vector, limit))
        return [{"id": uuid4(), "source_id": s, "source_title": "Synthetic", "page_from": 1,
                 "page_to": 1, "heading": "Chest", "text": "effusion", "score": 0.03,
                 "block_refs": [{"page": 1, "block": 1}]}
                for s in db.sources if db.owned(user, s)][:limit]

    async def figures(session: Any, user: UUID, query: str, **_: Any) -> Any:
        return [_figure_row(db, f) for f, (s, _k) in db.figures.items() if db.owned(user, s)]

    async def similar(session: Any, user: UUID, figure: UUID, limit: int) -> Any:
        source, _ = db.figures.get(figure, (uuid4(), ""))
        return [] if db.owned(user, source) else None

    monkeypatch.setattr(search, "hybrid_search", hybrid)
    monkeypatch.setattr(search, "search_figures", figures)
    monkeypatch.setattr(search, "similar_figures", similar)


client = TestClient(app)


def _upload(data: bytes = PDF, name: str = "chest.pdf") -> Any:
    return client.post("/v1/library/sources", files={"file": (name, data, "application/pdf")},
                       data={"title": "Synthetic chest"})


def _parsed_source(env: dict[str, Any]) -> tuple[UUID, UUID]:
    """Upload as the owner, then add one rendered page and one cropped figure."""
    source = UUID(_upload().json()["source_id"])
    page_key = storage.page_image_key(TENANT, source, 1)
    figure_key, figure = storage.figure_image_key(TENANT, source, 1, 0), uuid4()
    for key in (page_key, figure_key):
        env["store"].put(key, PNG, "image/png")
    env["db"].pages[(source, 1)] = page_key
    env["db"].figures[figure] = (source, figure_key)
    return source, figure


def test_requests_without_credentials_are_rejected() -> None:
    app.dependency_overrides.clear()  # the real principal dependency, no identity sent
    anonymous = TestClient(app)
    assert anonymous.get("/v1/library/sources").status_code == 401
    assert anonymous.post("/v1/library/search", json={"query": "effusion"}).status_code == 401
    assert anonymous.get(f"/v1/library/figures/{uuid4()}/image").status_code == 401


def test_upload_is_accepted_and_enqueues_exactly_one_ingest(env: dict[str, Any]) -> None:
    response = _upload()
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["duplicate"] is False
    source, job = UUID(body["source_id"]), UUID(body["job_id"])
    assert env["enqueued"] == [(TENANT, job)]
    assert list(env["store"].objects) == [storage.original_key(TENANT, source, "pdf")]
    assert env["db"].sources[source]["uploaded_by"] == OWNER.user_id


def test_duplicate_upload_returns_the_existing_source_and_enqueues_nothing(
    env: dict[str, Any],
) -> None:
    first = _upload().json()
    again = _upload(name="copy.pdf")
    assert again.status_code == 202
    assert again.json() == {"source_id": first["source_id"], "job_id": None, "duplicate": True}
    assert len(env["enqueued"]) == 1 and len(env["store"].objects) == 1


@pytest.mark.parametrize("data", [DICOM, b"synthetic plain notes"])
def test_dicom_and_unknown_bytes_are_415(env: dict[str, Any], data: bytes) -> None:
    assert _upload(data, "study.pdf").status_code == 415
    assert env["enqueued"] == [] and env["store"].objects == {} and env["db"].sources == {}


def test_upload_over_the_size_limit_is_413(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 64)
    assert _upload().status_code == 413
    assert env["enqueued"] == [] and env["store"].objects == {}


def test_list_and_detail_show_only_the_callers_sources(env: dict[str, Any]) -> None:
    source = _upload().json()["source_id"]
    listed = client.get("/v1/library/sources").json()
    assert [(s["id"], s["title"], s["kind"]) for s in listed] == [
        (source, "Synthetic chest", "pdf")]
    detail = client.get(f"/v1/library/sources/{source}")
    assert detail.status_code == 200
    assert detail.json()["steps"] == [] and "storage_key" not in detail.json()
    for other in (PEER, STRANGER):
        Who.principal = other
        assert client.get("/v1/library/sources").json() == []


@pytest.mark.parametrize("other", [PEER, STRANGER], ids=["same-tenant", "other-tenant"])
def test_another_users_source_is_404_everywhere(env: dict[str, Any], other: Principal) -> None:
    source, figure = _parsed_source(env)
    Who.principal = other
    for path in (f"sources/{source}", f"sources/{source}/pages/1",
                 f"sources/{source}/pages/1/image", f"figures/{figure}/image",
                 f"figures/{figure}/similar"):
        assert client.get(f"/v1/library/{path}").status_code == 404, path
    assert client.delete(f"/v1/library/sources/{source}").status_code == 404
    assert source in env["db"].sources and len(env["store"].objects) == 3


def test_delete_is_204_then_404_and_removes_the_objects(env: dict[str, Any]) -> None:
    source, _ = _parsed_source(env)
    assert client.delete(f"/v1/library/sources/{source}").status_code == 204
    assert env["store"].objects == {} and source not in env["db"].sources
    assert client.delete(f"/v1/library/sources/{source}").status_code == 404
    assert client.get(f"/v1/library/sources/{source}").status_code == 404


def test_delete_under_legal_hold_is_409_and_keeps_everything(env: dict[str, Any]) -> None:
    source, _ = _parsed_source(env)
    env["db"].sources[source]["legal_hold"] = True
    assert client.delete(f"/v1/library/sources/{source}").status_code == 409
    assert source in env["db"].sources and len(env["store"].objects) == 3


def test_page_and_figure_images_are_private_png(env: dict[str, Any]) -> None:
    source, figure = _parsed_source(env)
    assert client.get(f"/v1/library/sources/{source}/pages/1").json()["page_no"] == 1
    assert client.get(f"/v1/library/sources/{source}/pages/2/image").status_code == 404
    for path in (f"sources/{source}/pages/1/image", f"figures/{figure}/image"):
        response = client.get(f"/v1/library/{path}")
        assert response.status_code == 200 and response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"].startswith("private")


def test_a_key_outside_the_callers_tenant_is_never_served(env: dict[str, Any]) -> None:
    source, figure = _parsed_source(env)
    foreign = storage.figure_image_key(TENANT_B, uuid4(), 1, 0)
    env["store"].put(foreign, b"\x89PNG foreign tenant bytes", "image/png")
    env["db"].figures[figure] = (source, foreign)
    response = TestClient(app, raise_server_exceptions=False).get(
        f"/v1/library/figures/{figure}/image")
    # fetch_image refuses the key; the route answers as if the image were absent.
    assert response.status_code == 404 and b"foreign" not in response.content
    assert response.headers.get("content-type") != "image/png"


def test_search_returns_cited_hits_without_a_query_vector(env: dict[str, Any]) -> None:
    source, figure = _parsed_source(env)
    response = client.post("/v1/library/search", json={"query": "pleural effusion", "limit": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dense"] is False and body["query"] == "pleural effusion"
    assert env["searched"] == [(OWNER.user_id, "pleural effusion", None, 5)]
    citation = body["hits"][0]["citation"]
    assert (citation["source_id"], citation["page_from"]) == (str(source), 1)
    assert citation["block_refs"] == [{"page": 1, "block": 1}]
    assert body["figures"][0]["image_path"] == f"/v1/library/figures/{figure}/image"
    Who.principal = STRANGER
    assert client.post("/v1/library/search", json={"query": "effusion"}).json()["hits"] == []


@pytest.mark.parametrize("body", [
    {"query": "a"}, {"query": "x" * 501}, {"query": "effusion", "tenant_id": str(TENANT_B)},
    {"query": "effusion", "limit": 0}, {"query": "effusion", "limit": 31}, {},
])
def test_search_request_validation_is_422(env: dict[str, Any], body: dict[str, Any]) -> None:
    assert client.post("/v1/library/search", json=body).status_code == 422
    assert env["searched"] == []


def test_similar_figures_limit_bounds_are_422(env: dict[str, Any]) -> None:
    _, figure = _parsed_source(env)
    assert client.get(f"/v1/library/figures/{figure}/similar?limit=8").json() == []
    for limit in (0, 25):
        response = client.get(f"/v1/library/figures/{figure}/similar?limit={limit}")
        assert response.status_code == 422
