"""Deepen the assessment engine: item statistics, duplicate detection, async grading.

Expand-only (hard rule 5): additive, nullable or defaulted columns on
``questions`` (normalised stem for trigram similarity, stem embedding with an
HNSW index, status reason) and ``exams`` (free-text answers), plus two new tenant-scoped tables,
``item_stats`` and ``grading_jobs``, each with ENABLE + FORCE row-level
security and a two-tenant runtime-role proof in
``evals/checks/test_assessment_depth_live.py``. No cross-tenant resolver is
added: statistics are recomputed per user inside that user's tenant context.

Revision ID: 20260926_0011
Revises: 20260926_0010
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0011"
down_revision = "20260926_0010"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("item_stats", "grading_jobs")


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
    _expand_questions_and_exams()
    _create_tables()
    _create_policies()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON item_stats, grading_jobs TO {_RUNTIME_ROLE};"
    )


def _expand_questions_and_exams() -> None:
    execute_script(
        r"""
        ALTER TABLE questions ADD COLUMN IF NOT EXISTS stem_norm text
            CHECK (stem_norm IS NULL OR length(stem_norm) <= 8000);
        ALTER TABLE questions ADD COLUMN IF NOT EXISTS embedding vector(1024);
        ALTER TABLE questions ADD COLUMN IF NOT EXISTS embed_model text
            CHECK (embed_model IS NULL OR length(embed_model) <= 100);
        ALTER TABLE questions ADD COLUMN IF NOT EXISTS status_reason text
            CHECK (status_reason IS NULL OR length(status_reason) <= 100);
        ALTER TABLE questions ADD COLUMN IF NOT EXISTS status_changed_at timestamptz;

        UPDATE questions
        SET stem_norm = btrim(regexp_replace(lower(stem), '[^[:alnum:]]+', ' ', 'g'))
        WHERE stem_norm IS NULL;

        CREATE INDEX IF NOT EXISTS questions_embedding_idx
            ON questions USING hnsw (embedding vector_cosine_ops);

        ALTER TABLE exams ADD COLUMN IF NOT EXISTS text_answers jsonb NOT NULL
            DEFAULT '{}'::jsonb CHECK (jsonb_typeof(text_answers) = 'object');
        """
    )


def _create_tables() -> None:
    execute_script(
        """
        CREATE TABLE item_stats (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            question_id uuid NOT NULL,
            user_id uuid NOT NULL,
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            correct integer NOT NULL DEFAULT 0 CHECK (correct >= 0 AND correct <= attempts),
            p_value numeric(6, 4) CHECK (p_value IS NULL OR p_value BETWEEN 0 AND 1),
            discrimination numeric(6, 4)
                CHECK (discrimination IS NULL OR discrimination BETWEEN -1 AND 1),
            discrimination_n integer NOT NULL DEFAULT 0 CHECK (discrimination_n >= 0),
            decision text NOT NULL DEFAULT 'insufficient'
                CHECK (decision IN ('insufficient', 'keep', 'retire')),
            reason text CHECK (reason IS NULL OR length(reason) <= 100),
            last_computed timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, question_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, question_id) REFERENCES questions(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE TABLE grading_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            exam_id uuid NOT NULL,
            question_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'graded', 'failed')),
            runs integer NOT NULL DEFAULT 0 CHECK (runs >= 0),
            errors integer NOT NULL DEFAULT 0 CHECK (errors >= 0),
            error_code text CHECK (error_code IS NULL OR length(error_code) <= 60),
            grader text NOT NULL CHECK (length(grader) BETWEEN 1 AND 100),
            pipeline_version integer NOT NULL DEFAULT 1 CHECK (pipeline_version >= 1),
            result jsonb CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, exam_id, question_id, pipeline_version),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, exam_id) REFERENCES exams(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, question_id) REFERENCES questions(tenant_id, id)
                ON DELETE CASCADE,
            CHECK (status <> 'graded' OR result IS NOT NULL)
        );

        CREATE INDEX item_stats_owner_idx ON item_stats (tenant_id, user_id, decision);
        CREATE INDEX grading_jobs_open_idx ON grading_jobs (tenant_id, exam_id)
            WHERE status IN ('pending', 'running');
        CREATE TRIGGER grading_jobs_touch_updated_at
            BEFORE UPDATE ON grading_jobs
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
        DROP TABLE IF EXISTS grading_jobs;
        DROP TABLE IF EXISTS item_stats;
        ALTER TABLE exams DROP COLUMN IF EXISTS text_answers;
        DROP INDEX IF EXISTS questions_embedding_idx;
        ALTER TABLE questions DROP COLUMN IF EXISTS status_changed_at;
        ALTER TABLE questions DROP COLUMN IF EXISTS status_reason;
        ALTER TABLE questions DROP COLUMN IF EXISTS embed_model;
        ALTER TABLE questions DROP COLUMN IF EXISTS embedding;
        ALTER TABLE questions DROP COLUMN IF EXISTS stem_norm;
        """
    )
