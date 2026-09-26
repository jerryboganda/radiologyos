"""Every user-owned table, how to select one user's rows, and how they are erased.

This is the single inventory behind account export and account deletion
(ADR 0018). ``apps/api/tests/test_data_rights.py`` parses every migration and
fails when a table exists that is neither listed here nor explicitly exempt, so
a new tenant table cannot silently escape export or deletion.

Predicates are constant SQL over alias ``t`` with the bound parameter ``:u``
(the user id); they always run inside the tenant's RLS transaction, so they can
never reach another tenant even if a predicate were too broad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Erasure = Literal["direct", "sources", "source_cascade", "exports", "identity"]

MY_SOURCES = "SELECT id FROM sources WHERE uploaded_by = :u"
MY_CLAIMS = f"SELECT id FROM claims WHERE source_id IN ({MY_SOURCES})"  # nosec B608
MY_EMBEDDED_TEXT = (
    f"t.content_sha256 IN (SELECT content_sha256 FROM chunks WHERE source_id IN "  # nosec B608
    f"({MY_SOURCES})) OR t.content_sha256 IN (SELECT content_sha256 FROM figures "
    f"WHERE source_id IN ({MY_SOURCES}))"
)
# Constant subqueries; the only value is the bound :u.
MY_CONCEPTS = (
    f"SELECT concept_id FROM claims WHERE source_id IN ({MY_SOURCES}) "  # nosec B608
    f"UNION SELECT from_concept FROM concept_edges WHERE source_id IN ({MY_SOURCES}) "
    f"UNION SELECT to_concept FROM concept_edges WHERE source_id IN ({MY_SOURCES}) "
    # Concepts merged into one of these keep their names (ADR 0030).
    f"UNION SELECT k.id FROM concepts k JOIN claims c ON c.concept_id = k.merged_into "
    f"WHERE c.source_id IN ({MY_SOURCES})"
)


@dataclass(frozen=True, slots=True)
class Owned:
    table: str
    where: str
    erased_by: Erasure


OWNED: tuple[Owned, ...] = (
    Owned("users", "t.id = :u", "identity"),
    Owned("memberships", "t.user_id = :u", "identity"),
    Owned("audit_log", "t.actor_user_id = :u", "identity"),
    Owned("sources", "t.uploaded_by = :u", "sources"),
    Owned("jobs", f"t.entity_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("job_steps", f"t.entity_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("source_pages", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("source_blocks", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("figures", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("chunks", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    # Structured rows of this user's table blocks (ADR 0030).
    Owned("source_tables", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    # Cached vectors of this user's texts; purge_source_rows garbage-collects
    # cache rows no chunk or figure of the tenant still uses (ADR 0019).
    Owned("embedding_cache", MY_EMBEDDED_TEXT, "source_cascade"),
    Owned("concepts", f"t.id IN ({MY_CONCEPTS})", "source_cascade"),
    Owned("claims", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("concept_edges", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("knowledge_conflicts", f"t.claim_a IN ({MY_CLAIMS}) OR t.claim_b IN ({MY_CLAIMS})",
          "source_cascade"),
    Owned("curriculum_mappings", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("knowledge_runs", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    # Items of the user's sources waiting for the owner's Opus approval (ADR 0037).
    Owned("model_escalations", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("topic_frequencies", "t.user_id = :u", "direct"),
    # Synthesis notes and Resolver decisions recorded for this user (ADR 0030).
    Owned("concept_notes", "t.user_id = :u", "direct"),
    Owned("concept_merges", "t.user_id = :u", "direct"),
    Owned("topic_weights", "t.user_id = :u", "direct"),
    Owned("tutor_threads", "t.user_id = :u", "direct"),
    Owned("tutor_messages", "t.thread_id IN (SELECT id FROM tutor_threads WHERE user_id = :u)",
          "direct"),
    # Images attached to tutor questions; their objects live under
    # storage.tutor_image_prefix and are exported and erased with the rows (ADR 0025).
    Owned("tutor_images", "t.user_id = :u", "direct"),
    Owned("study_profiles", "t.user_id = :u", "direct"),
    Owned("study_plans", "t.user_id = :u", "direct"),
    Owned("cards", "t.user_id = :u", "direct"),
    Owned("card_reviews", "t.user_id = :u", "direct"),
    Owned("questions", "t.user_id = :u", "direct"),
    Owned("exams", "t.user_id = :u", "direct"),
    Owned("attempts", "t.user_id = :u", "direct"),
    Owned("push_subscriptions", "t.user_id = :u", "direct"),
    Owned("notification_settings", "t.user_id = :u", "direct"),
    Owned("baseline_tests", "t.user_id = :u", "direct"),
    Owned("weekly_reports", "t.user_id = :u", "direct"),
    Owned("item_stats", "t.user_id = :u", "direct"),
    Owned("grading_jobs", "t.user_id = :u", "direct"),
    Owned("viva_sessions", "t.user_id = :u", "direct"),
    Owned("viva_turns", "t.user_id = :u", "direct"),
    Owned("study_sessions", "t.user_id = :u", "direct"),
    Owned("study_session_steps", "t.user_id = :u", "direct"),
    Owned("weakness_events", "t.user_id = :u", "direct"),
    # A user's disputes of auto-graded exam points (ADR 0029); resolver ids stay.
    Owned("grade_disputes", "t.user_id = :u", "direct"),
    Owned("data_jobs", "t.user_id = :u", "exports"),
    # Tenant curriculum/blueprint decisions carry the deciding user's id (ADR 0023).
    Owned("curriculum_reviews", "t.decided_by = :u", "direct"),
    Owned("exam_blueprints", "t.updated_by = :u OR t.approved_by = :u", "direct"),
    # Model-call ledger rows made on the user's behalf: ids and numbers only (ADR 0032).
    Owned("llm_calls", "t.user_id = :u", "direct"),
)

# Tables that hold no row belonging to a single user.
EXEMPT: dict[str, str] = {
    "tenants": "tenant row; erase_user_identity renames and marks it deleted when "
               "its last user is erased",
    "embedding_usage": "per-tenant daily token counters for the Voyage budget; numbers "
                       "only, no user content (ADR 0019)",
    "ops_alerts": "tenant budget alerts with numeric detail only; no user content",
}

# Children before parents, so no foreign key blocks a delete. Rows of held
# sources' cascades stay; the user's own study rows never do.
DIRECT_DELETE_ORDER: tuple[str, ...] = (
    "concept_notes", "concept_merges",
    "grade_disputes", "viva_turns", "viva_sessions",
    "study_session_steps", "study_sessions", "weakness_events",
    "grading_jobs", "item_stats", "baseline_tests", "weekly_reports",
    "card_reviews", "attempts", "exams", "cards", "questions", "study_plans",
    "study_profiles", "tutor_messages", "tutor_threads", "tutor_images", "topic_weights",
    "topic_frequencies", "push_subscriptions", "notification_settings",
    "curriculum_reviews", "exam_blueprints", "llm_calls",
)


def owned(table: str) -> Owned:
    return next(item for item in OWNED if item.table == table)


def select_sql(item: Owned) -> str:
    """Rows of one table as JSON text, for the export."""
    return f"SELECT row_to_json(t)::text AS row FROM {item.table} t WHERE {item.where}"  # nosec B608 - constant table and predicate from this module


def delete_sql(table: str) -> str:
    item = owned(table)
    if item.erased_by != "direct":
        raise ValueError("table is not erased directly")
    return f"DELETE FROM {item.table} t WHERE {item.where}"  # nosec B608 - constant table and predicate from this module
