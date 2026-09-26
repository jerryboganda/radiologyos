"""Seeding and cleanup for the data-rights live proof (synthetic content only)."""

from __future__ import annotations

import os
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from packages.library import storage

ADMIN = "RADBRAIN_RLS_ADMIN_DATABASE_URL"
RUNTIME = "RADBRAIN_RLS_RUNTIME_DATABASE_URL"
# Children first, so the admin cleanup never trips a foreign key.
ALL_TABLES = (
    "llm_calls", "embedding_cache", "data_jobs", "curriculum_reviews", "exam_blueprints",
    "concept_notes", "concept_merges", "source_tables",
    "grade_disputes", "viva_turns", "viva_sessions",
    "study_session_steps", "study_sessions", "weakness_events", "grading_jobs",
    "item_stats", "baseline_tests", "weekly_reports",
    "card_reviews", "attempts", "exams", "cards", "questions", "study_plans",
    "study_profiles", "tutor_messages", "tutor_threads", "tutor_images", "topic_weights",
    "topic_frequencies",
    "push_subscriptions", "notification_settings", "knowledge_conflicts", "concept_edges",
    "claims", "curriculum_mappings", "knowledge_runs", "concepts", "chunks", "figures",
    "source_blocks", "source_pages", "job_steps", "jobs", "audit_log", "sources",
    "memberships", "users",
)


def require_env() -> tuple[str, str]:
    if ADMIN not in os.environ or RUNTIME not in os.environ:
        if os.environ.get("RADBRAIN_RLS_REQUIRED") == "1":
            pytest.fail("data-rights live proof requires disposable admin/runtime URLs")
        pytest.skip("set disposable admin/runtime PostgreSQL URLs to run this proof")
    return os.environ[ADMIN], os.environ[RUNTIME]


async def as_tenant(conn: Any, tenant: UUID | None, sql: str, *args: Any) -> Any:
    async with conn.transaction():
        if tenant is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return await conn.fetch(sql, *args)


async def seed_identity(
    admin: Any, tenant: UUID, user: UUID, source: UUID, held: bool = False
) -> None:
    async with admin.transaction():
        await admin.execute("INSERT INTO tenants (id, kind, name) VALUES ($1,'personal',$2)",
                            tenant, f"Rights {str(tenant)[:8]}")
        await admin.execute(
            "INSERT INTO users (id, tenant_id, oidc_subject, email, display_name) "
            "VALUES ($1,$2,$3,$4,'Synthetic Person')",
            user, tenant, f"rights-{user}", f"{user}@example.invalid")
        await admin.execute("INSERT INTO memberships (tenant_id, user_id, role) "
                            "VALUES ($1,$2,'student')", tenant, user)
        await admin.execute(
            "INSERT INTO sources (id, tenant_id, uploaded_by, kind, scope, sha256, storage_key, "
            "title, original_filename, legal_hold) VALUES ($1,$2,$3,'pdf','private',$4,$5,"
            "'Synthetic chest notes','chest notes.pdf',$6)",
            source, tenant, user, uuid4().hex + uuid4().hex,
            storage.original_key(tenant, source, "pdf"), held)


def seed_objects(store: storage.MemoryObjectStore, tenant: UUID, source: UUID) -> None:
    store.put(storage.original_key(tenant, source, "pdf"), b"%PDF-synthetic", "application/pdf")
    store.put(storage.page_image_key(tenant, source, 1), b"page-png", "image/png")
    store.put(storage.figure_image_key(tenant, source, 1, 0), b"figure-png", "image/png")


def tutor_image_id(user: UUID) -> UUID:
    """The synthetic tutor image seeded for ``user`` (ADR 0025)."""
    return uuid5(NAMESPACE_URL, f"radbrain-test:tutor-image:{user}")


def seed_tutor_image_object(store: storage.MemoryObjectStore, tenant: UUID, user: UUID) -> str:
    key = storage.tutor_image_key(tenant, user, tutor_image_id(user), "png")
    store.put(key, b"tutor-png", "image/png")
    return key


async def _library(conn: Any, t: UUID, u: UUID, s: UUID) -> dict[str, Any]:
    job = await conn.fetchval(
        "INSERT INTO jobs (tenant_id, entity_id, kind, idempotency_key) "
        "VALUES ($1,$2,'ingest_source',$3) RETURNING id", t, s, f"ingest:{s}")
    await conn.execute(
        "INSERT INTO job_steps (tenant_id, job_id, entity_id, step, pipeline_version, status) "
        "VALUES ($1,$2,$3,'chunk',1,'succeeded')", t, job, s)
    await conn.execute(
        "INSERT INTO source_pages (tenant_id, source_id, page_no, image_key, native_text) "
        "VALUES ($1,$2,1,$3,'Synthetic page')", t, s, storage.page_image_key(t, s, 1))
    await conn.execute(
        "INSERT INTO source_blocks (tenant_id, source_id, page_no, block_no, kind, text, bbox, "
        "origin) VALUES ($1,$2,1,0,'paragraph','Synthetic block','{0,0,1,1}','native')", t, s)
    await conn.execute(
        "INSERT INTO figures (tenant_id, source_id, page_no, figure_no, bbox, image_key, caption) "
        "VALUES ($1,$2,1,0,'{0,0,1,1}',$3,'Synthetic figure')",
        t, s, storage.figure_image_key(t, s, 1, 0))
    chunk = await conn.fetchval(
        "INSERT INTO chunks (tenant_id, source_id, chunk_no, page_from, page_to, text, embedding, "
        "content_sha256) VALUES ($1,$2,0,1,1,'Synthetic chunk text',"
        "array_fill(0.01::real, ARRAY[1024])::vector, repeat('a', 64)) RETURNING id", t, s)
    await conn.execute(
        "INSERT INTO embedding_cache (tenant_id, content_sha256, model, dimensions, embedding) "
        "VALUES ($1, repeat('a', 64), 'voyage-4-large', 1024, "
        "array_fill(0.01::real, ARRAY[1024])::vector)", t)
    await conn.execute("INSERT INTO audit_log (tenant_id, actor_user_id, action, target_type, "
                       "target_id) VALUES ($1,$2,'source.uploaded','source',$3)", t, u, str(s))
    return {"chunk": chunk}


async def _knowledge(conn: Any, t: UUID, u: UUID, s: UUID, chunk: UUID) -> None:
    cite = f'{{"source_id": "{s}", "page_from": 1, "page_to": 1}}'
    concepts = [await conn.fetchval(
        "INSERT INTO concepts (tenant_id, name, normalized_name) VALUES ($1,$2,$3) RETURNING id",
        t, name, name.lower()) for name in ("Synthetic UIP", "Synthetic sign")]
    claims = [await conn.fetchval(
        "INSERT INTO claims (tenant_id, concept_id, statement, evidence_span, source_id, "
        "chunk_id, page_from, page_to, citation, agent_version) VALUES "
        "($1,$2,$3,'synthetic span',$4,$5,1,1,$6::jsonb,'test') RETURNING id",
        t, concepts[0], f"Synthetic claim {n}", s, chunk, cite) for n in (1, 2)]
    await conn.execute(
        "INSERT INTO concept_edges (tenant_id, from_concept, to_concept, relation, claim_id, "
        "source_id, citation, agent_version) VALUES ($1,$2,$3,'sign_of',$4,$5,$6::jsonb,'t')",
        t, concepts[1], concepts[0], claims[0], s, cite)
    await conn.execute(
        "INSERT INTO knowledge_conflicts (tenant_id, concept_id, claim_a, claim_b, kind, "
        "description) VALUES ($1,$2,$3,$4,'numeric','Synthetic conflict')",
        t, concepts[0], claims[0], claims[1])
    await conn.execute(
        "INSERT INTO curriculum_mappings (tenant_id, source_id, unit_hash, chunk_id, page_from, "
        "page_to, curriculum_code, confidence, status, agent_version) VALUES "
        "($1,$2,'abcdef12',$3,1,1,'CHEST',0.5,'review','t')", t, s, chunk)
    await conn.execute(
        "INSERT INTO knowledge_runs (tenant_id, source_id, unit, agent_version, "
        "pipeline_version, status) VALUES ($1,$2,'chunk:0','t',1,'succeeded')", t, s)
    await conn.execute(
        "INSERT INTO topic_frequencies (tenant_id, user_id, source_id, page_no, exam_target, "
        "curriculum_code, count, agent_version) VALUES ($1,$2,$3,1,'imm','CHEST',1,'t')", t, u, s)
    await conn.execute(
        "INSERT INTO topic_weights (tenant_id, user_id, exam_target, curriculum_code, weight, "
        "basis) VALUES ($1,$2,'imm','CHEST',0.5,'{}'::jsonb)", t, u)
    await _depth(conn, t, u, s, concepts)


async def _depth(conn: Any, t: UUID, u: UUID, s: UUID, concepts: list[UUID]) -> None:
    """ADR 0030 rows: a cited note, a Resolver decision, and a structured table."""
    await conn.execute(
        "INSERT INTO concept_notes (tenant_id, user_id, concept_id, version, claims_hash, body, "
        "sentences, agent_version) VALUES ($1,$2,$3,1,repeat('b', 64),'{}'::jsonb,1,'t')",
        t, u, concepts[0])
    low, high = sorted(concepts)
    await conn.execute(
        "INSERT INTO concept_merges (tenant_id, user_id, concept_a, concept_b, similarity, "
        "decision, confidence, rationale, status, agent_version) VALUES "
        "($1,$2,$3,$4,0.85,'distinct',0.9,'Synthetic','distinct','t')", t, u, low, high)
    await conn.execute(
        "INSERT INTO source_tables (tenant_id, source_id, page_no, block_no, bbox, n_rows, "
        "n_cols, cells, csv, html, plain) VALUES ($1,$2,1,0,'{0,0,1,1}',1,2,"
        "'[[\"a\",\"b\"]]','a,b','<table></table>','a b')", t, s)


async def _study(conn: Any, t: UUID, u: UUID, s: UUID, chunk: UUID) -> None:
    cite = f'{{"source_id": "{s}", "page_from": 1, "page_to": 1}}'
    await conn.execute("INSERT INTO study_profiles (tenant_id, user_id, exam_date) "
                       "VALUES ($1,$2,'2027-01-01')", t, u)
    await conn.execute(
        "INSERT INTO study_plans (tenant_id, user_id, plan_date, phase, days_remaining, "
        "minutes, plan_version, blocks) VALUES ($1,$2,current_date,'coverage',90,60,1,"
        "'[]'::jsonb)", t, u)
    card = await conn.fetchval(
        "INSERT INTO cards (tenant_id, user_id, source_id, source_chunk_id, curriculum_code, "
        "topic, front, back, citation) VALUES ($1,$2,$3,$4,'CHEST','Synthetic topic',"
        "'Synthetic front?','Synthetic back.',$5::jsonb) RETURNING id", t, u, s, chunk, cite)
    await conn.execute(
        "INSERT INTO card_reviews (tenant_id, user_id, card_id, rating, elapsed_days, "
        "scheduled_days, state_before, stability_after, difficulty_after) "
        "VALUES ($1,$2,$3,3,0,1,'new',1,5)", t, u, card)
    question = await conn.fetchval(
        "INSERT INTO questions (tenant_id, user_id, type, stem, answer, citations, "
        "agent_version) VALUES ($1,$2,'seq','Synthetic stem?','{}'::jsonb,$3::jsonb,'t') "
        "RETURNING id", t, u, f"[{cite}]")
    exam = await conn.fetchval(
        "INSERT INTO exams (tenant_id, user_id, mode, question_ids) "
        "VALUES ($1,$2,'practice',ARRAY[$3::uuid]) RETURNING id", t, u, question)
    await conn.execute(
        "INSERT INTO attempts (tenant_id, user_id, question_id, exam_id, response, score, "
        "max_score, graded_by) VALUES ($1,$2,$3,$4,'{}'::jsonb,1,2,'t')", t, u, question, exam)
    await conn.execute(
        "INSERT INTO baseline_tests (tenant_id, user_id, exam_id, question_ids, systems) "
        "VALUES ($1,$2,$3,ARRAY[$4::uuid],'{}'::jsonb)", t, u, exam, question)
    await conn.execute(
        "INSERT INTO weekly_reports (tenant_id, user_id, week_start, report_version, report) "
        "VALUES ($1,$2,date '2026-09-21',1,'{}'::jsonb)", t, u)
    await conn.execute(
        "INSERT INTO item_stats (tenant_id, question_id, user_id) VALUES ($1,$2,$3)",
        t, question, u)
    await conn.execute(
        "INSERT INTO grading_jobs (tenant_id, user_id, exam_id, question_id, grader) "
        "VALUES ($1,$2,$3,$4,'seq_grade/v1')", t, u, exam, question)
    thread = await conn.fetchval("INSERT INTO tutor_threads (tenant_id, user_id, title) "
                                 "VALUES ($1,$2,'Synthetic thread') RETURNING id", t, u)
    image = tutor_image_id(u)
    await conn.execute(
        "INSERT INTO tutor_images (id, tenant_id, user_id, storage_key, content_type, "
        "byte_size, width, height, sha256) VALUES ($1,$2,$3,$4,'image/png',9,1,1,repeat('b',64))",
        image, t, u, storage.tutor_image_key(t, u, image, "png"))
    await conn.execute("INSERT INTO tutor_messages (tenant_id, thread_id, role, content, "
                       "image_id) VALUES ($1,$2,'user','Synthetic question',$3)",
                       t, thread, image)
    await conn.execute(
        "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth) "
        "VALUES ($1,$2,$3,repeat('p',20),'authauthauth')",
        t, u, f"https://push.example.invalid/{u}")
    await conn.execute("INSERT INTO notification_settings (tenant_id, user_id) VALUES ($1,$2)",
                       t, u)


async def seed_content(runtime: Any, tenant: UUID, user: UUID, source: UUID) -> None:
    """One row in every user-owned table, written as the runtime role."""
    async with runtime.transaction():
        await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        ids = await _library(runtime, tenant, user, source)
        await _knowledge(runtime, tenant, user, source, ids["chunk"])
        await _study(runtime, tenant, user, source, ids["chunk"])
        await runtime.execute(
            "INSERT INTO curriculum_reviews (tenant_id, pack_id, pack_version, content_hash, "
            "decision, decided_by) VALUES ($1,'radiology','t',repeat('a',64),'approved',$2)",
            tenant, user)
        await runtime.execute(
            "INSERT INTO exam_blueprints (tenant_id, blueprint_id, updated_by) "
            "VALUES ($1,'frcr_2a',$2)", tenant, user)
        await runtime.execute(
            "INSERT INTO llm_calls (tenant_id, user_id, agent, route, backend, model, effort, "
            "status, duration_ms) VALUES ($1,$2,'tutor_answer/v3','reason','claude_code',"
            "'synthetic-model','high','ok',1200)", tenant, user)


async def counts(admin: Any, tenant: UUID) -> dict[str, int]:
    return {table: await admin.fetchval(
        f"SELECT count(*) FROM {table} WHERE tenant_id = $1", tenant)  # nosec B608
        for table in ALL_TABLES}


async def cleanup(admin: Any, tenants: list[UUID]) -> None:
    async with admin.transaction():
        for table in ALL_TABLES:
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tenants)
        await admin.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", tenants)
