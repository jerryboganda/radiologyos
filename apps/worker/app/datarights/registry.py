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
# Constant subqueries; the only value is the bound :u.
MY_CONCEPTS = (
    f"SELECT concept_id FROM claims WHERE source_id IN ({MY_SOURCES}) "  # nosec B608
    f"UNION SELECT from_concept FROM concept_edges WHERE source_id IN ({MY_SOURCES}) "
    f"UNION SELECT to_concept FROM concept_edges WHERE source_id IN ({MY_SOURCES})"
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
    Owned("concepts", f"t.id IN ({MY_CONCEPTS})", "source_cascade"),
    Owned("claims", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("concept_edges", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("knowledge_conflicts", f"t.claim_a IN ({MY_CLAIMS}) OR t.claim_b IN ({MY_CLAIMS})",
          "source_cascade"),
    Owned("curriculum_mappings", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("knowledge_runs", f"t.source_id IN ({MY_SOURCES})", "source_cascade"),
    Owned("topic_frequencies", "t.user_id = :u", "direct"),
    Owned("topic_weights", "t.user_id = :u", "direct"),
    Owned("tutor_threads", "t.user_id = :u", "direct"),
    Owned("tutor_messages", "t.thread_id IN (SELECT id FROM tutor_threads WHERE user_id = :u)",
          "direct"),
    Owned("study_profiles", "t.user_id = :u", "direct"),
    Owned("study_plans", "t.user_id = :u", "direct"),
    Owned("cards", "t.user_id = :u", "direct"),
    Owned("card_reviews", "t.user_id = :u", "direct"),
    Owned("questions", "t.user_id = :u", "direct"),
    Owned("exams", "t.user_id = :u", "direct"),
    Owned("attempts", "t.user_id = :u", "direct"),
    Owned("push_subscriptions", "t.user_id = :u", "direct"),
    Owned("notification_settings", "t.user_id = :u", "direct"),
    Owned("data_jobs", "t.user_id = :u", "exports"),
)

# Tables that hold no row belonging to a single user.
EXEMPT: dict[str, str] = {
    "tenants": "tenant row; erase_user_identity renames and marks it deleted when "
               "its last user is erased",
}

# Children before parents, so no foreign key blocks a delete. Rows of held
# sources' cascades stay; the user's own study rows never do.
DIRECT_DELETE_ORDER: tuple[str, ...] = (
    "card_reviews", "attempts", "exams", "cards", "questions", "study_plans",
    "study_profiles", "tutor_messages", "tutor_threads", "topic_weights",
    "topic_frequencies", "push_subscriptions", "notification_settings",
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
