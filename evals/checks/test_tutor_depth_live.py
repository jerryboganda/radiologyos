"""Opt-in live proof for tutor depth (migration 0017, ADR 0025).

Runs in CI against a disposable PostgreSQL as the RLS-bound runtime role:
* ``tutor_images`` hides tenant A's rows from tenant B and from a session with
  no tenant, rejects a foreign tenant_id and a storage key outside the owner's
  prefix, and cannot be attached to another tenant's message (composite FK);
* only user messages carry an image, and the real repositories keep images,
  rolling memory, and Reader-page retrieval scoped to their owner.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest

asyncpg: Any = pytest.importorskip("asyncpg")

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
IMAGE_SQL = ("INSERT INTO tutor_images (id, tenant_id, user_id, storage_key, content_type, "
             "byte_size, width, height, sha256) VALUES ($1,$2,$3,$4,'image/png',9,1,1,"
             "repeat('c',64))")


def _require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("tutor depth live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run the tutor depth proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


def _key(tenant: UUID, user: UUID, image: UUID) -> str:
    return f"tenants/{tenant}/tutor-images/{user}/{image}.png"


async def _seed(admin: Any) -> dict[str, UUID]:
    ids = {name: uuid4() for name in ("ta", "tb", "ua", "ua2", "ub", "sa", "ia", "tha")}
    async with admin.transaction():
        await admin.execute("INSERT INTO tenants (id, kind, name) VALUES "
                            "($1,'personal','Depth A'),($2,'personal','Depth B')",
                            ids["ta"], ids["tb"])
        for user, tenant in (("ua", "ta"), ("ua2", "ta"), ("ub", "tb")):
            await admin.execute(
                "INSERT INTO users (id, tenant_id, oidc_subject, email) VALUES ($1,$2,$3,$4)",
                ids[user], ids[tenant], f"depth-{ids[user]}", f"{ids[user]}@example.invalid")
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, "
            "storage_key, title) VALUES ($1,$2,$3,'pdf','private',$4,$5,'Synthetic deck')",
            ids["sa"], ids["ta"], ids["ua"], uuid4().hex + uuid4().hex,
            f"tenants/{ids['ta']}/sources/{ids['sa']}/original.pdf")
    return ids


async def _cleanup(admin: Any, ids: dict[str, UUID]) -> None:
    tenants = [ids["ta"], ids["tb"]]
    async with admin.transaction():
        for table in ("tutor_messages", "tutor_threads", "tutor_images", "chunks", "sources",
                      "users"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])",
                                tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)


async def _as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def _rls_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb, ua, ia = ids["ta"], ids["tb"], ids["ua"], ids["ia"]
    await _as_tenant(runtime, ta, IMAGE_SQL, ia, ta, ua, _key(ta, ua, ia))
    assert await _as_tenant(runtime, tb, "SELECT 1 FROM tutor_images") == []
    assert await _as_tenant(runtime, None, "SELECT 1 FROM tutor_images") == []
    assert len(await _as_tenant(runtime, ta, "SELECT 1 FROM tutor_images")) == 1
    assert await _as_tenant(runtime, tb, "UPDATE tutor_images SET byte_size = 1 RETURNING 1") \
        == []
    assert await _as_tenant(runtime, tb, "DELETE FROM tutor_images RETURNING 1") == []
    other = uuid4()
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await _as_tenant(runtime, tb, IMAGE_SQL, other, ta, ua, _key(ta, ua, other))
    with pytest.raises(asyncpg.exceptions.CheckViolationError):  # key outside the prefix
        await _as_tenant(runtime, ta, IMAGE_SQL, other, ta, ua, _key(tb, ua, other))
    with pytest.raises(asyncpg.exceptions.CheckViolationError):  # another user's prefix
        await _as_tenant(runtime, ta, IMAGE_SQL, other, ta, ua, _key(ta, ids["ua2"], other))


async def _message_proof(runtime: Any, ids: dict[str, UUID]) -> None:
    ta, tb = ids["ta"], ids["tb"]
    await _as_tenant(runtime, ta, "INSERT INTO tutor_threads (id, tenant_id, user_id, title) "
                     "VALUES ($1,$2,$3,'Synthetic')", ids["tha"], ta, ids["ua"])
    message = ("INSERT INTO tutor_messages (tenant_id, thread_id, role, content, image_id, "
               "grounding) VALUES ($1,$2,$3,'Synthetic',$4,$5)")
    await _as_tenant(runtime, ta, message, ta, ids["tha"], "user", ids["ia"], None)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _as_tenant(runtime, ta, message, ta, ids["tha"], "assistant", ids["ia"], "none")
    thread_b = uuid4()
    await _as_tenant(runtime, tb, "INSERT INTO tutor_threads (id, tenant_id, user_id, title) "
                     "VALUES ($1,$2,$3,'Synthetic')", thread_b, tb, ids["ub"])
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await _as_tenant(runtime, tb, message, tb, thread_b, "user", ids["ia"], None)


async def _repo_proof(runtime_dsn: str, ids: dict[str, UUID]) -> None:
    from apps.api.app.library import search
    from apps.api.app.tutor import images, repo
    from apps.worker.app.ingest.db import tenant_tx
    from packages.library.parse_models import ImageCase
    from packages.tutor.memory import MemoryUpdate
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    reading = ImageCase(modality="CT", anatomy="chest", visible_text="", findings=["GGO"],
                        impression="PAP", differentials=[], teaching_points=[], topics=[],
                        confidence="low")
    engine = create_async_engine(runtime_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        async with tenant_tx(engine, ids["ta"]) as session:
            await session.execute(text(
                "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, page_to, text) "
                "VALUES (:t, :s, 0, 7, 8, 'Synthetic dural tail')"),
                {"t": ids["ta"], "s": ids["sa"]})
            await images.save_reading(session, ids["ia"], reading, "image_case/v1")
            await repo.save_memory(session, ids["tha"], MemoryUpdate("Synthetic summary", 1,
                                                                     "tutor_memory/v1"))
        async with tenant_tx(engine, ids["ta"]) as session:
            own = await images.get_image(session, ids["ua"], ids["ia"])
            colleague = await images.get_image(session, ids["ua2"], ids["ia"])
            memory = await repo.memory_state(session, ids["tha"])
            page = await search.page_chunks(session, ids["ua"], ids["sa"], 8, 4)
            title = await search.source_title(session, ids["ua"], ids["sa"])
            stranger_page = await search.page_chunks(session, ids["ua2"], ids["sa"], 8, 4)
            messages = await repo.thread_messages(session, ids["tha"])
        async with tenant_tx(engine, ids["tb"]) as session:
            assert await images.get_image(session, ids["ub"], ids["ia"]) is None
            assert (await repo.memory_state(session, ids["tha"])).uncovered == ()
            assert await search.source_title(session, ids["ub"], ids["sa"]) is None
    finally:
        await engine.dispose()
    assert own is not None and images.stored_reading(own["reading"]) == reading
    assert colleague is None and stranger_page == []
    assert memory.summary == "Synthetic summary" and memory.covered == 1
    assert memory.uncovered == ()  # the only message is covered by the summary
    assert [p["page_from"] for p in page] == [7] and title == "Synthetic deck"
    assert messages[0]["image_id"] == ids["ia"]
    assert images.stored_reading(messages[0]["image_reading"]) == reading


async def _run() -> None:
    admin_dsn, runtime_dsn = _require_env()
    admin = await asyncpg.connect(admin_dsn)
    runtime = await asyncpg.connect(runtime_dsn)
    ids = await _seed(admin)
    try:
        await _rls_proof(runtime, ids)
        await _message_proof(runtime, ids)
        await _repo_proof(runtime_dsn, ids)
    finally:
        await runtime.close()
        await _cleanup(admin, ids)
        await admin.close()


def test_tutor_depth_tables_and_repositories_against_runtime_role() -> None:
    _require_env()
    asyncio.run(_run())
