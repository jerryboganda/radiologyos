"""Daily study loop: Today sessions, the weakness loop, and SBA confidence (ADR 0024).

Expand-only (hard rule 5):

* three new tenant-scoped tables, ``study_sessions``, ``study_session_steps`` and
  ``weakness_events``, each with ENABLE + FORCE row-level security and a
  two-tenant runtime-role proof in ``evals/checks/test_study_sessions_live.py``;
* a nullable ``attempts.confidence`` column (1 low, 2 medium, 3 high);
* the ``cards.origin`` check is widened to also allow ``weakness``: the
  constraint is replaced in one statement by a strictly wider one, so every row
  and every writer of the previous release stays valid (no column is dropped or
  renamed, and nothing stops being written).

No cross-tenant resolver is added: sessions are built on request inside the
caller's tenant context, and completion clears tomorrow's cached plan so the
existing nightly replan rebuilds it from fresh mastery.

Revision ID: 20260926_0016
Revises: 20260926_0014
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0016"
down_revision = "20260926_0014"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("study_sessions", "study_session_steps", "weakness_events")


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
    _create_sessions()
    _create_weakness()
    _expand_attempts_and_cards()
    _create_policies()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {_RUNTIME_ROLE};"
    )


def _create_sessions() -> None:
    execute_script(
        """
        CREATE TABLE study_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            session_date date NOT NULL,
            session_version integer NOT NULL CHECK (session_version >= 1),
            plan_version integer NOT NULL CHECK (plan_version >= 1),
            status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed')),
            summary jsonb CHECK (summary IS NULL OR jsonb_typeof(summary) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, user_id, session_date),
            CHECK ((status = 'completed') = (completed_at IS NOT NULL)),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE
        );

        CREATE TABLE study_session_steps (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            session_id uuid NOT NULL,
            user_id uuid NOT NULL,
            step_no smallint NOT NULL CHECK (step_no BETWEEN 1 AND 20),
            kind text NOT NULL CHECK (kind IN ('review', 'learn', 'test', 'viva')),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'done', 'skipped')),
            minutes integer NOT NULL CHECK (minutes >= 0),
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result) = 'object'),
            started_at timestamptz,
            deadline_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, session_id, step_no),
            CHECK (deadline_at IS NULL OR started_at IS NOT NULL),
            FOREIGN KEY (tenant_id, session_id) REFERENCES study_sessions(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE
        );

        CREATE INDEX study_sessions_user_idx
            ON study_sessions (tenant_id, user_id, session_date DESC);
        CREATE INDEX study_session_steps_user_idx
            ON study_session_steps (tenant_id, user_id, kind, status);
        CREATE TRIGGER study_sessions_touch_updated_at BEFORE UPDATE ON study_sessions
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER study_session_steps_touch_updated_at BEFORE UPDATE ON study_session_steps
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_weakness() -> None:
    execute_script(
        """
        CREATE TABLE weakness_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('sba_wrong', 'exam_wrong', 'card_lapse')),
            ref_id uuid NOT NULL,
            question_id uuid,
            card_id uuid,
            curriculum_code text
                CHECK (curriculum_code IS NULL OR length(curriculum_code) BETWEEN 1 AND 64),
            retest_by timestamptz NOT NULL,
            retested_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, kind, ref_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, question_id) REFERENCES questions(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, card_id) REFERENCES cards(tenant_id, id)
                ON DELETE SET NULL (card_id)
        );

        CREATE INDEX weakness_events_open_idx ON weakness_events (tenant_id, user_id, retest_by)
            WHERE retested_at IS NULL;
        CREATE INDEX weakness_events_question_idx
            ON weakness_events (tenant_id, user_id, question_id);
        """
    )


def _expand_attempts_and_cards() -> None:
    execute_script(
        """
        ALTER TABLE attempts ADD COLUMN IF NOT EXISTS confidence smallint
            CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 3);

        -- Widen the origin check (a strict superset of the old one).
        ALTER TABLE cards
            DROP CONSTRAINT IF EXISTS cards_origin_check,
            ADD CONSTRAINT cards_origin_check
                CHECK (origin IN ('manual', 'generated', 'weakness'));
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
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                ) WITH CHECK (
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                );
            """
        )


def downgrade() -> None:
    execute_script(
        """
        DELETE FROM cards WHERE origin = 'weakness';
        ALTER TABLE cards
            DROP CONSTRAINT IF EXISTS cards_origin_check,
            ADD CONSTRAINT cards_origin_check CHECK (origin IN ('manual', 'generated'));
        ALTER TABLE attempts DROP COLUMN IF EXISTS confidence;
        DROP TABLE IF EXISTS weakness_events;
        DROP TABLE IF EXISTS study_session_steps;
        DROP TABLE IF EXISTS study_sessions;
        """
    )
