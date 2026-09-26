"""Add the study engine tables: profiles, cards, card reviews, daily plans.

Expand-only (hard rule 5): four new tables, nothing dropped or renamed. Every
table is tenant-scoped with ENABLE + FORCE row-level security and a two-tenant
negative proof in evals/checks/test_study_live.py. Cards must carry a citation
that resolves to their source (hard rule 3); deleting a source deletes the
cards derived from it, as it already deletes its pages, blocks, and chunks.

Revision ID: 20260926_0006
Revises: 20260926_0005
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0006"
down_revision = "20260926_0005"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("study_profiles", "cards", "card_reviews", "study_plans")
_STATES = "('new', 'learning', 'review', 'relearning')"


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
    _create_profiles_and_plans()
    _create_cards()
    _create_reviews()
    _create_policies()
    execute_script(
        f"""
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON study_profiles, cards, study_plans TO {_RUNTIME_ROLE};
        GRANT SELECT, INSERT, DELETE ON card_reviews TO {_RUNTIME_ROLE};
        """
    )


def _create_profiles_and_plans() -> None:
    execute_script(
        """
        CREATE TABLE study_profiles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            exam_date date NOT NULL,
            exam_targets text[] NOT NULL DEFAULT '{}'::text[] CHECK (
                exam_targets <@ ARRAY['fcps2_theory', 'fcps2_toacs', 'imm', 'frcr']::text[]
            ),
            daily_minutes integer NOT NULL DEFAULT 90
                CHECK (daily_minutes BETWEEN 15 AND 600),
            weekday_minutes integer
                CHECK (weekday_minutes IS NULL OR weekday_minutes BETWEEN 0 AND 600),
            weekend_minutes integer
                CHECK (weekend_minutes IS NULL OR weekend_minutes BETWEEN 0 AND 600),
            timezone text NOT NULL DEFAULT 'UTC'
                CHECK (length(timezone) BETWEEN 1 AND 64),
            reminder jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(reminder) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE TABLE study_plans (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            plan_date date NOT NULL,
            phase text NOT NULL CHECK (phase IN (
                'coverage', 'coverage_consolidation', 'consolidation', 'exam_mode', 'taper'
            )),
            days_remaining integer NOT NULL CHECK (days_remaining >= 0),
            minutes integer NOT NULL CHECK (minutes >= 0),
            plan_version integer NOT NULL CHECK (plan_version >= 1),
            blocks jsonb NOT NULL CHECK (jsonb_typeof(blocks) = 'array'),
            detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
            generated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id, plan_date),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE TRIGGER study_profiles_touch_updated_at
            BEFORE UPDATE ON study_profiles
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_cards() -> None:
    execute_script(
        f"""
        CREATE TABLE cards (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            source_id uuid NOT NULL,
            source_chunk_id uuid,
            curriculum_code text NOT NULL
                CHECK (curriculum_code ~ '^[A-Z0-9][A-Z0-9._-]*$'),
            topic text NOT NULL CHECK (length(btrim(topic)) BETWEEN 1 AND 200),
            front text NOT NULL CHECK (length(btrim(front)) BETWEEN 1 AND 2000),
            back text NOT NULL CHECK (length(btrim(back)) BETWEEN 1 AND 4000),
            origin text NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'generated')),
            citation jsonb NOT NULL CHECK (
                jsonb_typeof(citation) = 'object'
                AND citation->>'source_id' = source_id::text
                AND (citation->>'page_from') IS NOT NULL
                AND (citation->>'page_to') IS NOT NULL
            ),
            state text NOT NULL DEFAULT 'new' CHECK (state IN {_STATES}),
            stability double precision NOT NULL DEFAULT 0 CHECK (stability >= 0),
            difficulty double precision NOT NULL DEFAULT 0
                CHECK (difficulty = 0 OR difficulty BETWEEN 1 AND 10),
            due_at timestamptz NOT NULL DEFAULT now(),
            last_review_at timestamptz,
            reps integer NOT NULL DEFAULT 0 CHECK (reps >= 0),
            lapses integer NOT NULL DEFAULT 0 CHECK (lapses >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX cards_due_idx ON cards (tenant_id, user_id, due_at);
        CREATE INDEX cards_topic_idx ON cards (tenant_id, user_id, curriculum_code);
        CREATE INDEX cards_source_idx ON cards (tenant_id, source_id);

        CREATE TRIGGER cards_touch_updated_at
            BEFORE UPDATE ON cards
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_reviews() -> None:
    execute_script(
        f"""
        CREATE TABLE card_reviews (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            card_id uuid NOT NULL,
            rating smallint NOT NULL CHECK (rating BETWEEN 1 AND 4),
            reviewed_at timestamptz NOT NULL DEFAULT now(),
            elapsed_days integer NOT NULL CHECK (elapsed_days >= 0),
            scheduled_days integer NOT NULL CHECK (scheduled_days >= 0),
            state_before text NOT NULL CHECK (state_before IN {_STATES}),
            stability_after double precision NOT NULL CHECK (stability_after >= 0),
            difficulty_after double precision NOT NULL
                CHECK (difficulty_after BETWEEN 1 AND 10),
            retrievability double precision
                CHECK (retrievability IS NULL OR retrievability BETWEEN 0 AND 1),
            FOREIGN KEY (tenant_id, card_id) REFERENCES cards(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
        );

        CREATE INDEX card_reviews_user_idx ON card_reviews (tenant_id, user_id, reviewed_at);
        CREATE INDEX card_reviews_card_idx ON card_reviews (tenant_id, card_id);
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
        DROP TABLE IF EXISTS card_reviews;
        DROP TABLE IF EXISTS cards;
        DROP TABLE IF EXISTS study_plans;
        DROP TABLE IF EXISTS study_profiles;
        """
    )
