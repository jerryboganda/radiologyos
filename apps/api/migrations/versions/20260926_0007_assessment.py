"""Add the persistent assessment engine: questions, exams, attempts.

Expand-only (hard rule 5): three new tenant-scoped tables and one additive
unique index on ``figures``; nothing is dropped or renamed. Every new table has
ENABLE + FORCE row-level security and a two-tenant runtime-role proof in
``evals/checks/test_assessment_live.py``. Attempts are append-only for the
runtime role (no UPDATE grant).

Revision ID: 20260926_0007
Revises: 20260926_0006
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0007"
down_revision = "20260926_0006"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("questions", "exams", "attempts")


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

        CREATE UNIQUE INDEX IF NOT EXISTS figures_tenant_id_id_uq ON figures (tenant_id, id);
        """
    )
    _create_questions()
    _create_exams_and_attempts()
    _create_policies()
    execute_script(
        f"""
        GRANT SELECT, INSERT, UPDATE, DELETE ON questions, exams TO {_RUNTIME_ROLE};
        GRANT SELECT, INSERT, DELETE ON attempts TO {_RUNTIME_ROLE};
        """
    )


def _create_questions() -> None:
    execute_script(
        """
        CREATE TABLE questions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            type text NOT NULL
                CHECK (type IN ('sba', 'seq', 'image_case', 'viva', 'rapid_recall')),
            exam_tags text[] NOT NULL DEFAULT '{}'::text[] CHECK (
                exam_tags <@ ARRAY['fcps2_theory', 'fcps2_toacs', 'imm', 'frcr']::text[]
            ),
            topic text NOT NULL DEFAULT '' CHECK (length(topic) <= 300),
            stem text NOT NULL CHECK (length(stem) > 0 AND length(stem) <= 8000),
            options jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(options) = 'array'),
            answer jsonb NOT NULL CHECK (jsonb_typeof(answer) = 'object'),
            explanation text NOT NULL DEFAULT '',
            citations jsonb NOT NULL CHECK (
                jsonb_typeof(citations) = 'array' AND jsonb_array_length(citations) > 0
            ),
            figure_id uuid,
            status text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'retired')),
            quality jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(quality) = 'object'),
            agent_version text NOT NULL CHECK (length(agent_version) BETWEEN 1 AND 100),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, figure_id) REFERENCES figures(tenant_id, id)
                ON DELETE SET NULL (figure_id),
            CHECK (type <> 'sba' OR (jsonb_array_length(options) = 5
                AND answer->>'key' IS NOT NULL))
        );

        CREATE INDEX questions_owner_idx ON questions (tenant_id, user_id, status, type);
        CREATE INDEX questions_exam_tags_idx ON questions USING gin (exam_tags);
        CREATE TRIGGER questions_touch_updated_at
            BEFORE UPDATE ON questions
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_exams_and_attempts() -> None:
    execute_script(
        """
        CREATE TABLE exams (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            mode text NOT NULL CHECK (mode IN ('practice', 'exam')),
            config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
            question_ids uuid[] NOT NULL
                CHECK (cardinality(question_ids) BETWEEN 1 AND 300),
            started_at timestamptz NOT NULL DEFAULT now(),
            deadline_at timestamptz,
            submitted_at timestamptz,
            revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
            answers jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(answers) = 'object'),
            result jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            CHECK (mode = 'practice' OR deadline_at IS NOT NULL),
            CHECK (deadline_at IS NULL OR deadline_at > started_at),
            CHECK ((submitted_at IS NULL) = (result IS NULL))
        );

        CREATE TABLE attempts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            question_id uuid NOT NULL,
            exam_id uuid,
            response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
            score numeric(8, 2) NOT NULL CHECK (score >= 0),
            max_score numeric(8, 2) NOT NULL CHECK (max_score > 0 AND score <= max_score),
            feedback jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(feedback) = 'object'),
            graded_by text NOT NULL CHECK (length(graded_by) BETWEEN 1 AND 100),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, question_id) REFERENCES questions(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, exam_id) REFERENCES exams(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX exams_owner_idx ON exams (tenant_id, user_id, created_at DESC);
        CREATE INDEX exams_open_idx ON exams USING gin (question_ids)
            WHERE submitted_at IS NULL;
        CREATE INDEX attempts_question_idx ON attempts (tenant_id, question_id, created_at);
        CREATE INDEX attempts_owner_idx ON attempts (tenant_id, user_id, created_at DESC);
        CREATE UNIQUE INDEX attempts_exam_question_uq ON attempts (tenant_id, exam_id, question_id)
            WHERE exam_id IS NOT NULL;
        CREATE TRIGGER exams_touch_updated_at
            BEFORE UPDATE ON exams
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
        DROP TABLE IF EXISTS attempts;
        DROP TABLE IF EXISTS exams;
        DROP TABLE IF EXISTS questions;
        DROP INDEX IF EXISTS figures_tenant_id_id_uq;
        """
    )
