"""M1 eval gate: durable ingestion, provenance, and cited, owner-scoped search.

Covers slices E-H of the A-Z queue against the durable implementation:
  E  upload (format by content, sha256 dedupe, size limit, DICOM refusal), tenant
     keys, and a versioned idempotent job whose steps all report visible status
  F  the real worker pipeline (``apps/worker/app/ingest/steps.py``) over a
     synthetic PDF, plus bounded heading-aware chunking of a large document
  G  page -> block -> chunk provenance and bounding-box quality gates
  H  search, the page reader, and delete, whose SQL is scoped to the uploading
     user and excludes deleted sources

Database effects are emulated in memory (the worker's ``db`` modules are swapped
for a tenant-checking fake; API-side SQL is captured, not executed). The
row-level RLS proof for the same tables and SQL runs in CI as
``evals/checks/test_library_live.py``. All content is synthetic.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from apps.api.app.library import reader, search, service
from apps.api.app.security.principal import Principal
from apps.api.tests.pdf_fixture import make_pdf
from apps.worker.app.ingest import steps
from apps.worker.app.job_id import IngestStep, JobId
from packages.library import storage
from packages.library.chunking import MAX_WORDS, BlockInput, build_chunks, looks_like_heading
from packages.library.formats import UnsupportedUpload
from packages.library.parse_models import PageParse, ParsedBlock, ParsedFigure
from packages.library.quality import bbox_ok, page_parse_problem

TENANT_A = UUID("30000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("30000000-0000-0000-0000-00000000000b")
OWNER_A = UUID("10000000-0000-0000-0000-00000000000a")
CHEST_PAGES = [
    ["Chest radiography", "A pleural effusion blunts the costophrenic angle."],
    ["Mediastinum", "Loss of the hilar point suggests hilar lymphadenopathy."],
]
DICOM = b"\x00" * 128 + b"DICM" + b"\x00" * 64
GATED = {"extract_tables": "tables_are_blocks", "embed_index": "no_embedding_key",
         "parse_layout": "no_model_transport", "extract_figures": "no_model_transport"}
Handler = Callable[[str, dict[str, Any]], list[dict[str, Any]]]


class Rows(list[dict[str, Any]]):
    """Enough of SQLAlchemy's Result for the library code paths."""
    def mappings(self) -> Rows:
        return self
    scalars = mappings
    def first(self) -> dict[str, Any] | None:
        return self[0] if self else None
    def scalar_one_or_none(self) -> Any:
        return next(iter(self[0].values())) if self else None
    scalar_one = scalar_one_or_none
    def all(self) -> list[Any]:
        return [next(iter(r.values())) for r in self]


class CaptureSession:
    """Records every statement and its bound parameters; answers via a handler."""
    def __init__(self, handler: Handler | None = None) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.handler = handler or (lambda sql, params: [])
        self.commits = 0
    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Rows:
        sql, bound = " ".join(str(statement).split()), dict(params or {})
        self.statements.append((sql, bound))
        return Rows(self.handler(sql, bound))
    async def commit(self) -> None:
        self.commits += 1


class MemoryIngestDB:
    """Stands in for ``ingest.db``/``ingest.db_content``. A transaction is its
    tenant id; every call asserts the row it touches is in that tenant (RLS)."""
    def __init__(self) -> None:
        self.jobs: dict[UUID, dict[str, Any]] = {}
        self.sources: dict[UUID, dict[str, Any]] = {}
        self.steps: dict[tuple[UUID, str, int], dict[str, Any]] = {}
        self.pages: dict[tuple[UUID, int], dict[str, Any]] = {}
        self.blocks: dict[tuple[UUID, int], list[dict[str, Any]]] = {}
        self.chunks: dict[UUID, list[Any]] = {}
    @asynccontextmanager
    async def tenant_tx(self, engine: Any, tenant_id: UUID) -> AsyncIterator[UUID]:
        yield tenant_id
    def _source(self, tx: UUID, source_id: UUID) -> dict[str, Any]:
        assert self.sources[source_id]["tenant_id"] == tx, "row outside the tx tenant"
        return self.sources[source_id]
    async def load_job(self, tx: UUID, job_id: UUID) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        return dict(job) if job and job["tenant_id"] == tx else None
    async def load_source(self, tx: UUID, source_id: UUID) -> dict[str, Any] | None:
        row = self.sources.get(source_id)
        return dict(row) if row and row["tenant_id"] == tx else None
    async def set_job_status(self, tx: UUID, job_id: UUID, status: str, code: Any = None) -> None:
        assert self.jobs[job_id]["tenant_id"] == tx
        self.jobs[job_id].update(status=status, error_code=code)
    async def mark_step(self, tx: UUID, job: dict[str, Any], step: str, status: str,
                        error_code: str | None = None, output_ref: str | None = None) -> None:
        assert job["tenant_id"] == tx
        row = self.steps.setdefault((job["id"], step, job["pipeline_version"]),
                                    {"attempts": 0, "output_ref": None})
        row.update(status=status, error_code=error_code,
                   output_ref=output_ref or row["output_ref"],
                   attempts=row["attempts"] + (status == "running"))
    async def step_status(self, tx: UUID, job_id: UUID, step: str) -> str | None:
        found = [r["status"] for (j, s, _), r in self.steps.items() if (j, s) == (job_id, step)]
        return found[0] if found else None
    async def upsert_page(self, tx: UUID, values: dict[str, Any]) -> None:
        assert values["tenant_id"] == self._source(tx, values["source_id"])["tenant_id"]
        key = (values["source_id"], values["page_no"])
        self.pages[key] = {**self.pages.get(key, {"vision_status": "pending"}), **values}
    async def replace_blocks(self, tx: UUID, tenant_id: UUID, source_id: UUID, page_no: int,
                             blocks: list[dict[str, Any]]) -> None:
        assert tenant_id == tx and (source_id, page_no) in self.pages
        self.blocks[(source_id, page_no)] = [dict(b) for b in blocks]
    async def set_source_status(self, tx: UUID, source_id: UUID, status: str,
                                page_count: int | None = None) -> None:
        row = self._source(tx, source_id)
        row.update(status=status, page_count=page_count or row.get("page_count"))
    async def blocks_of(self, tx: UUID, source_id: UUID) -> list[dict[str, Any]]:
        self._source(tx, source_id)
        return [{k: b[k] for k in ("block_no", "kind", "text")} | {"page_no": p}
                for (s, p), blocks in sorted(self.blocks.items(), key=lambda i: i[0][1])
                if s == source_id for b in blocks]
    async def replace_chunks(self, tx: UUID, tenant_id: UUID, source_id: UUID,
                             chunks: list[Any]) -> int:
        assert tenant_id == self._source(tx, source_id)["tenant_id"]
        self.chunks[source_id] = list(chunks)
        return len(chunks)
    async def pages_of(self, tx: UUID, source_id: UUID) -> list[dict[str, Any]]:
        return [dict(p) for (s, _), p in sorted(self.pages.items()) if s == source_id]


@pytest.fixture
def worker_db(monkeypatch: pytest.MonkeyPatch) -> MemoryIngestDB:
    fake = MemoryIngestDB()
    content = type("Content", (), {"blocks": fake.blocks_of, "pages": fake.pages_of,
                                   "replace_chunks": fake.replace_chunks})
    monkeypatch.setattr(steps, "db", fake)
    monkeypatch.setattr(steps, "db_content", content)
    return fake


async def _ingest(fake: MemoryIngestDB) -> tuple[dict[str, Any], steps.Deps]:
    """Seed one uploaded synthetic PDF and run the real pipeline over it."""
    store, source_id, job_id = storage.MemoryObjectStore(), uuid4(), uuid4()
    key = storage.original_key(TENANT_A, source_id, "pdf")
    store.put(key, make_pdf(CHEST_PAGES), "application/pdf")
    fake.sources[source_id] = {"id": source_id, "tenant_id": TENANT_A, "kind": "pdf",
                               "storage_key": key, "title": "Synthetic", "status": "uploaded",
                               "page_count": None}
    fake.jobs[job_id] = {"id": job_id, "tenant_id": TENANT_A, "entity_id": source_id,
                         "pipeline_version": 1, "status": "queued"}
    deps = steps.Deps(engine=cast(Any, None), store=store, transport=None, embedder=None)
    assert await steps.run_ingest(deps, TENANT_A, job_id) == "succeeded"
    return fake.jobs[job_id], deps


async def test_every_canonical_step_is_visible_and_a_rerun_resumes(
    worker_db: MemoryIngestDB,
) -> None:
    job, deps = await _ingest(worker_db)
    recorded = {step: row for (_, step, _), row in worker_db.steps.items()}
    # Knowledge extraction is handed to its own task only after a vision pass.
    assert set(recorded) == {s.value for s in IngestStep} - {"knowledge_extraction"}
    assert not [s for s, r in recorded.items() if r["status"] in {"pending", "running"}]
    for step, reason in GATED.items():  # gated work says why, never fakes success
        assert (recorded[step]["status"], recorded[step]["error_code"]) == ("skipped", reason)
    assert recorded["render_pages"]["output_ref"] == "pages:2"
    assert job["status"] == "succeeded"
    assert worker_db.sources[job["entity_id"]]["status"] == "ready"
    store = cast(storage.MemoryObjectStore, deps.store)
    steps_before, objects = set(worker_db.steps), dict(store.objects)
    assert await steps.run_ingest(deps, TENANT_A, job["id"]) == "succeeded"
    assert store.objects == objects  # pages were not re-rendered
    assert set(worker_db.steps) == steps_before  # one row per (job, step, version)
    assert worker_db.steps[(job["id"], "render_pages", 1)]["attempts"] == 1
    # A job read under another tenant is invisible, so it cannot be driven.
    assert await steps.run_ingest(deps, TENANT_B, job["id"]) == "missing"


def test_job_identity_is_versioned_and_tenant_scoped() -> None:
    entity = uuid4()
    v1 = JobId.from_parts(TENANT_A, entity, IngestStep.CHUNK, 1)
    assert str(v1).endswith(":chunk:v1") and JobId.from_key(str(v1)) == v1
    assert str(JobId.from_parts(TENANT_A, entity, IngestStep.CHUNK, 2)) != str(v1)
    assert str(JobId.from_parts(TENANT_B, entity, IngestStep.CHUNK, 1)) != str(v1)
    for bad in (str(v1).rsplit(":", 1)[0], str(v1)[:-2] + "v0", str(v1).replace("chunk", "x")):
        with pytest.raises(ValueError):
            JobId.from_key(bad)
    with pytest.raises(ValueError):
        JobId.from_parts(TENANT_A, entity, IngestStep.CHUNK, 0)


def _upload_session() -> CaptureSession:
    """A tenant session whose ``sources`` table remembers inserted sha256 values."""
    existing: dict[str, UUID] = {}
    def handler(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if sql.startswith("SELECT id, title, status FROM sources WHERE sha256"):
            found = existing.get(params["h"])
            return [{"id": found, "title": "t", "status": "ready"}] if found else []
        if sql.startswith("INSERT INTO sources"):
            existing[params["sha"]] = params["id"]
        return []
    return CaptureSession(handler)


async def _create(session: CaptureSession, store: storage.ObjectStore, data: bytes,
                  name: str = "chest.pdf", limit: int = 10_000_000) -> dict[str, Any]:
    return await service.create_source(cast(Any, session), store, Principal(OWNER_A, TENANT_A),
                                       io.BytesIO(data), name, limit, 7)


def _inserts(session: CaptureSession, table: str) -> list[tuple[str, dict[str, Any]]]:
    return [(s, p) for s, p in session.statements if s.startswith(f"INSERT INTO {table} ")]


async def test_upload_records_a_versioned_job_and_dedupes_by_sha256() -> None:
    session, store = _upload_session(), storage.MemoryObjectStore()
    created = await _create(session, store, make_pdf(CHEST_PAGES))
    assert created["duplicate"] is False
    assert list(store.objects) == [storage.original_key(TENANT_A, created["source_id"], "pdf")]
    ((sql, source),) = _inserts(session, "sources")
    assert (source["t"], source["u"], source["kind"]) == (TENANT_A, OWNER_A, "pdf")
    assert "'private'" in sql
    ((_, job),) = _inserts(session, "jobs")
    assert job["key"] == f"ingest:{created['source_id']}:v7" and job["v"] == 7
    assert job["id"] == created["job_id"] and session.commits == 1
    again = await _create(session, store, make_pdf(CHEST_PAGES), name="renamed.pdf")
    assert again == {"duplicate": True, "source_id": created["source_id"], "job_id": None}
    assert len(store.objects) == len(_inserts(session, "jobs")) == 1 and session.commits == 1


@pytest.mark.parametrize("data", [b"", b"plain synthetic notes", DICOM,
                                  b"PK\x03\x04" + b"\x00" * 64])
async def test_empty_unknown_and_dicom_uploads_are_rejected(data: bytes) -> None:
    session, store = _upload_session(), storage.MemoryObjectStore()
    with pytest.raises(UnsupportedUpload):
        await _create(session, store, data, name="study.pdf")
    assert store.objects == {} and not _inserts(session, "sources")


async def test_uploads_over_the_limit_are_refused_before_storage() -> None:
    with pytest.raises(service.UploadTooLarge):
        service.spool_upload(io.BytesIO(b"x" * 11), 10)
    spooled, digest, size, head = service.spool_upload(io.BytesIO(b"x" * 10), 10)
    spooled.close()
    assert (size, head, len(digest)) == (10, b"x" * 10, 64)
    session, store = _upload_session(), storage.MemoryObjectStore()
    with pytest.raises(service.UploadTooLarge):
        await _create(session, store, make_pdf(CHEST_PAGES), limit=64)
    assert store.objects == {} and session.statements == []


def test_object_keys_are_tenant_prefixed_and_never_collide() -> None:
    source = UUID(int=1)
    keys_a = [storage.original_key(TENANT_A, source, "pdf"),
              storage.page_image_key(TENANT_A, source, 1),
              storage.figure_image_key(TENANT_A, source, 1, 0)]
    assert all(k.startswith(f"tenants/{TENANT_A}/sources/{source}/") for k in keys_a)
    assert storage.original_key(TENANT_B, source, "pdf") not in keys_a
    for key in keys_a:
        storage.require_tenant_key(TENANT_A, key)
        with pytest.raises(PermissionError):
            storage.require_tenant_key(TENANT_B, key)
    with pytest.raises(PermissionError):
        storage.require_tenant_key(TENANT_A, f"tenants/{TENANT_A}/../{TENANT_B}/x.png")
    with pytest.raises(PermissionError):  # the reader never fetches a foreign key
        reader.fetch_image(storage.MemoryObjectStore(), TENANT_B, keys_a[1])


async def test_pdf_pages_blocks_and_chunks_keep_provenance(worker_db: MemoryIngestDB) -> None:
    job, deps = await _ingest(worker_db)
    source_id = job["entity_id"]
    pages = [p for (s, _), p in sorted(worker_db.pages.items()) if s == source_id]
    assert [p["page_no"] for p in pages] == [1, 2]
    assert worker_db.sources[source_id]["page_count"] == 2
    for page, lines in zip(pages, CHEST_PAGES, strict=True):
        assert page["image_key"] == storage.page_image_key(TENANT_A, source_id, page["page_no"])
        assert deps.store.get(page["image_key"]).startswith(b"\x89PNG")
        assert page["text_origin"] == "native" and lines[1] in page["native_text"]
        blocks = worker_db.blocks[(source_id, page["page_no"])]
        assert [b["block_no"] for b in blocks] == list(range(len(blocks)))
        assert all(b["text"].strip() and bbox_ok(b["bbox"]) for b in blocks)
        # Heading detection: a short unpunctuated first line becomes a heading.
        assert blocks[0]["kind"] == "heading" and blocks[0]["text"] == lines[0]
    chunks = worker_db.chunks[source_id]
    assert chunks[0].heading == CHEST_PAGES[0][0]
    assert (chunks[0].page_from, chunks[-1].page_to) == (1, 2)
    for chunk in chunks:  # every chunk cites its page range and real block refs
        assert chunk.text.strip() and chunk.block_refs
        for ref in chunk.block_refs:
            assert chunk.page_from <= ref["page"] <= chunk.page_to
            texts = [b["text"] for b in worker_db.blocks[(source_id, ref["page"])]
                     if b["block_no"] == ref["block"]]
            assert texts and texts[0] in chunk.text


def test_chunking_stays_bounded_on_a_large_document() -> None:
    blocks: list[BlockInput] = []
    for i in range(1, 201):
        page, n = 1 + i // 10, (i % 10) * 2
        blocks += [BlockInput(page, n, "heading", f"Section {i}"),
                   BlockInput(page, n + 1, "paragraph",
                              f"Synthetic finding number {i} describes a pattern. " * 12)]
    chunks = build_chunks(blocks)
    assert 1 < len(chunks) < len(blocks)
    assert all(len(c.text.split()) <= MAX_WORDS for c in chunks)
    assert all(c.page_to - c.page_from < 3 and c.heading.startswith("Section") for c in chunks)
    assert [c.chunk_no for c in chunks] == list(range(len(chunks)))
    cited = [(r["page"], r["block"]) for c in chunks for r in c.block_refs]
    assert sorted(cited) == sorted((b.page_no, b.block_no) for b in blocks)
    assert looks_like_heading("Pulmonary alveolar proteinosis", 0)
    assert not looks_like_heading("Pulmonary alveolar proteinosis", 2)
    assert not looks_like_heading("A sentence that ends with a full stop.", 0)


def test_boxes_outside_the_page_or_inverted_are_rejected() -> None:
    assert bbox_ok([0.1, 0.1, 0.5, 0.4])
    for bad in ([0.5, 0.1, 0.1, 0.4], [0.0, 0.0, 1.2, 0.5], [0.1, 0.1, 0.2]):
        assert not bbox_ok(bad)
    figure = ParsedFigure(bbox=[0.1, 0.1, 1.5, 0.9], is_radiology_image=True, caption="",
                          modality="CT", anatomy="chest", description="d", findings=[])
    parsed = PageParse(page_type="mixed", figures=[figure], topics=[], blocks=[
        ParsedBlock(kind="paragraph", text="Synthetic", bbox=[0.1, 0.1, 0.9, 0.2])])
    assert page_parse_problem(parsed, None) == "bbox_out_of_range"
    native = " ".join(f"term{i}" for i in range(40))
    assert page_parse_problem(parsed.model_copy(update={"figures": []}), native) \
        == "low_text_coverage"


async def test_search_and_reader_sql_is_scoped_to_the_uploading_user() -> None:
    session = CaptureSession()
    assert await search.hybrid_search(cast(Any, session), OWNER_A, "effusion", [0.1] * 4) == []
    await search.search_figures(cast(Any, session), OWNER_A, "effusion", query_vector=[0.2] * 4)
    await search.similar_figures(cast(Any, session), OWNER_A, uuid4(), 5)
    await reader.read_page(cast(Any, session), OWNER_A, uuid4(), 1)
    await reader.image_key_for_page(cast(Any, session), OWNER_A, uuid4(), 1)
    await reader.image_key_for_figure(cast(Any, session), OWNER_A, uuid4())
    assert len(session.statements) == 8
    for sql, params in session.statements:
        assert "JOIN sources s" in sql and "s.uploaded_by = :u" in sql, sql
        assert "s.deleted_at IS NULL" in sql and params["u"] == OWNER_A
    # No statement takes a tenant id from the caller: RLS supplies the tenant.
    assert not [p for _, p in session.statements if TENANT_A in p.values()]


async def test_hybrid_search_fuses_ranks_and_returns_cited_hits() -> None:
    first, second, gone, source = uuid4(), uuid4(), uuid4(), uuid4()
    def handler(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "ts_rank_cd" in sql:
            return [{"id": first, "score": 0.9}, {"id": second, "score": 0.5}]
        if "<=>" in sql:
            return [{"id": second, "score": 0.8}, {"id": gone, "score": 0.7}]
        if "c.id = ANY(:ids)" in sql:  # ``gone`` was deleted between the two reads
            return [{"id": i, "source_id": source, "source_title": "Synthetic", "page_from": 1,
                     "page_to": 2, "heading": "Pleura", "text": "effusion",
                     "block_refs": [{"page": 1, "block": 0}]} for i in (first, second)]
        return []

    hits = await search.hybrid_search(cast(Any, CaptureSession(handler)), OWNER_A,
                                      "effusion", [0.1] * 4, limit=3)
    assert [h["id"] for h in hits] == [second, first]  # found by both paths ranks first
    assert hits[0]["matched"] == {"lexical": True, "dense": True}
    assert all(h["block_refs"] and h["source_id"] == source for h in hits)
    assert hits[0]["score"] > hits[1]["score"]


@pytest.mark.parametrize(("owned", "held"), [(True, False), (True, True), (False, False)])
async def test_delete_purges_only_the_owners_unheld_source(owned: bool, held: bool) -> None:
    source, other = uuid4(), uuid4()
    store = storage.MemoryObjectStore()
    for tenant, sid in ((TENANT_A, source), (TENANT_A, other), (TENANT_B, source)):
        store.put(storage.page_image_key(tenant, sid, 1), b"png", "image/png")
    def handler(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "FROM sources WHERE id = :id AND uploaded_by = :u" in sql:
            assert "deleted_at IS NULL" in sql and params["u"] == OWNER_A
            return [{"id": params["id"], "storage_key": "k"}] if owned else []
        return [{"legal_hold": held}] if sql.startswith("SELECT legal_hold") else []

    session, principal = CaptureSession(handler), Principal(OWNER_A, TENANT_A)
    if held:
        with pytest.raises(service.SourceOnHold):
            await service.delete_source(cast(Any, session), store, principal, source)
    else:
        assert await service.delete_source(cast(Any, session), store, principal, source) is owned
    removed = owned and not held
    assert (storage.page_image_key(TENANT_A, source, 1) not in store.objects) is removed
    assert len(store.objects) == (2 if removed else 3)  # other sources/tenants untouched
    purged = any(s.startswith("DELETE FROM sources") for s, _ in session.statements)
    assert purged is removed and session.commits == int(removed)
