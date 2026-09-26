"""Viva examiner sessions and staged TOACS image cases (ADR 0026).

Expand-only (hard rule 5): two new tenant-scoped tables and no change to any
existing column. ``viva_sessions`` holds one multi-turn viva or staged image
case (evidence as chunk/figure references only, never copied source text; the
frozen stage rubric; examiner state; the job fields the worker claims; the
final debrief). ``viva_turns`` holds each examiner question with its frozen,
cited expected points, the candidate's answer, and the evaluation. Both have
ENABLE + FORCE row-level security and a two-tenant runtime-role proof in
``evals/checks/test_viva_live.py``, and both are registered for export and
erasure in the data-rights registry.

Revision ID: 20260926_0018
Revises: 20260926_0014
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0018"
down_revision = "20260926_0014"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("viva_sessions", "viva_turns")
_STAGES = "'describe', 'findings', 'diagnosis', 'differentials', 'next_step'"


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
    _create_turns()
    _create_policies()
    execute_script(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} "
                   f"TO {_RUNTIME_ROLE};")


def _create_sessions() -> None:
    execute_script(
        """
        CREATE TABLE viva_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('viva', 'image_case')),
            style text NOT NULL DEFAULT 'practice'
                CHECK (style IN ('practice', 'fcps2_toacs', 'frcr_2b_oral')),
            topic text NOT NULL DEFAULT '' CHECK (length(topic) <= 300),
            figure_id uuid,
            question_id uuid,
            scenario text NOT NULL DEFAULT '' CHECK (length(scenario) <= 8000),
            evidence jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence) = 'array'),
            case_data jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(case_data) = 'object'),
            status text NOT NULL DEFAULT 'preparing'
                CHECK (status IN ('preparing', 'active', 'finished', 'failed')),
            work text NOT NULL DEFAULT 'none' CHECK (work IN ('none', 'pending', 'running')),
            work_turn integer NOT NULL DEFAULT 0 CHECK (work_turn >= 0),
            runs integer NOT NULL DEFAULT 0 CHECK (runs >= 0),
            errors integer NOT NULL DEFAULT 0 CHECK (errors >= 0),
            error_code text CHECK (error_code IS NULL OR length(error_code) <= 60),
            level integer NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
            miss_streak integer NOT NULL DEFAULT 0 CHECK (miss_streak >= 0),
            max_turns integer NOT NULL DEFAULT 8 CHECK (max_turns BETWEEN 1 AND 20),
            started_at timestamptz NOT NULL DEFAULT now(),
            deadline_at timestamptz,
            finished_at timestamptz,
            stop_reason text CHECK (stop_reason IS NULL OR stop_reason IN (
                'max_turns', 'time_up', 'two_consecutive_misses', 'ended_by_candidate',
                'stages_complete', 'examiner_error')),
            debrief jsonb CHECK (debrief IS NULL OR jsonb_typeof(debrief) = 'object'),
            pipeline_version integer NOT NULL DEFAULT 1 CHECK (pipeline_version >= 1),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, figure_id) REFERENCES figures(tenant_id, id)
                ON DELETE SET NULL (figure_id),
            FOREIGN KEY (tenant_id, question_id) REFERENCES questions(tenant_id, id)
                ON DELETE SET NULL (question_id),
            CHECK (deadline_at IS NULL OR deadline_at > started_at),
            CHECK ((status = 'finished') = (debrief IS NOT NULL AND finished_at IS NOT NULL)),
            CHECK (status <> 'finished' OR work = 'none')
        );

        CREATE INDEX viva_sessions_owner_idx
            ON viva_sessions (tenant_id, user_id, created_at DESC);
        CREATE INDEX viva_sessions_work_idx ON viva_sessions (tenant_id, updated_at)
            WHERE work <> 'none';
        CREATE TRIGGER viva_sessions_touch_updated_at
            BEFORE UPDATE ON viva_sessions
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_turns() -> None:
    execute_script(
        f"""
        CREATE TABLE viva_turns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            session_id uuid NOT NULL,
            turn_no integer NOT NULL CHECK (turn_no BETWEEN 1 AND 40),
            stage text CHECK (stage IS NULL OR stage IN ({_STAGES})),
            level integer NOT NULL CHECK (level BETWEEN 1 AND 5),
            move text NOT NULL CHECK (move IN ('open', 'escalate', 'probe', 'stage')),
            prompt text NOT NULL CHECK (length(prompt) BETWEEN 1 AND 4000),
            hint text NOT NULL DEFAULT '' CHECK (length(hint) <= 2000),
            expected jsonb NOT NULL CHECK (
                jsonb_typeof(expected) = 'array' AND jsonb_array_length(expected) > 0),
            answer_text text CHECK (answer_text IS NULL OR length(answer_text) <= 8000),
            answered_at timestamptz,
            status text NOT NULL DEFAULT 'asked'
                CHECK (status IN ('asked', 'answered', 'graded', 'skipped')),
            evaluation jsonb CHECK (evaluation IS NULL OR jsonb_typeof(evaluation) = 'object'),
            pipeline_version integer NOT NULL DEFAULT 1 CHECK (pipeline_version >= 1),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, session_id, turn_no),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, session_id) REFERENCES viva_sessions(tenant_id, id)
                ON DELETE CASCADE,
            CHECK (status <> 'graded' OR evaluation IS NOT NULL),
            CHECK (status NOT IN ('answered', 'graded') OR answer_text IS NOT NULL)
        );

        CREATE TRIGGER viva_turns_touch_updated_at
            BEFORE UPDATE ON viva_turns
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
        DROP TABLE IF EXISTS viva_turns;
        DROP TABLE IF EXISTS viva_sessions;
        """
    )
