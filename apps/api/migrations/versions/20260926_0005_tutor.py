"""Add durable grounded-tutor threads and messages (ADR 0013).

Expand-only (hard rule 5): two new tables, nothing dropped or renamed. Both are
tenant-scoped with ENABLE + FORCE row-level security and a two-tenant negative
proof in evals/checks/test_tutor_live.py. Messages reference their thread by
(tenant_id, thread_id), so a message can never attach to another tenant's
thread. ``citations`` holds the verified answer segments, each with its
citations; ``content`` holds plain text for display and history.

Revision ID: 20260926_0005
Revises: 20260926_0004
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("tutor_threads", "tutor_messages")


def upgrade() -> None:
    execute_script(
        f"""
        DO $$
        BEGIN
            IF current_user <> '{_MIGRATOR_ROLE}' THEN
                RAISE EXCEPTION 'migrations must run as %', '{_MIGRATOR_ROLE}';
            END IF;
        END
        $$;
        """
    )
    _create_tables()
    _create_policies()
    execute_script(
        f"""
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON tutor_threads, tutor_messages TO {_RUNTIME_ROLE};
        """
    )


def _create_tables() -> None:
    execute_script(
        """
        CREATE TABLE tutor_threads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE TABLE tutor_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            thread_id uuid NOT NULL,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL CHECK (length(content) BETWEEN 1 AND 100000),
            citations jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(citations) = 'array'),
            grounding text CHECK (grounding IN ('sources', 'web', 'mixed', 'none')),
            agent_version text NOT NULL DEFAULT ''
                CHECK (length(agent_version) <= 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, thread_id) REFERENCES tutor_threads(tenant_id, id)
                ON DELETE CASCADE,
            CHECK (
                (role = 'user' AND grounding IS NULL)
                OR (role = 'assistant' AND grounding IS NOT NULL)
            )
        );

        CREATE INDEX tutor_threads_user_idx
            ON tutor_threads (tenant_id, user_id, updated_at DESC);
        CREATE INDEX tutor_messages_thread_idx
            ON tutor_messages (tenant_id, thread_id, created_at);

        CREATE TRIGGER tutor_threads_touch_updated_at
            BEFORE UPDATE ON tutor_threads
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_policies() -> None:
    for table in TABLES:
        execute_script(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON {table} FROM PUBLIC;
            CREATE POLICY {table}_tenant_all ON {table}
                FOR ALL USING (
                    tenant_id = app.current_tenant_id()
                    AND tenant_id <> '{_CORE}'::uuid
                ) WITH CHECK (
                    tenant_id = app.current_tenant_id()
                    AND tenant_id <> '{_CORE}'::uuid
                );
            """
        )


def downgrade() -> None:
    execute_script(
        """
        DROP TABLE IF EXISTS tutor_messages;
        DROP TABLE IF EXISTS tutor_threads;
        """
    )
