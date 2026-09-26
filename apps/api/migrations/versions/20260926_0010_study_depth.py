"""Study depth: baseline diagnostics, weekly reports, and two beat resolvers.

Expand-only (hard rule 5): two new tenant-scoped tables, two narrow resolver
functions, and additive read policies for the migrator role; nothing is
dropped or renamed. Both tables have ENABLE + FORCE row-level security and a
two-tenant runtime-role proof in ``evals/checks/test_study_depth_live.py``.

The worker must know *which* users are due a weekly report or a nightly replan
without reading any tenant's data, so two SECURITY DEFINER functions (owned by
the migrator) return only (tenant_id, user_id) pairs; everything else is read
under that tenant's RLS context. A profile whose time zone PostgreSQL does not
know is skipped rather than failing the whole resolver.

Revision ID: 20260926_0010
Revises: 20260926_0009
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0010"
down_revision = "20260926_0009"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("baseline_tests", "weekly_reports")
_RESOLVER_READS = ("study_profiles", "study_plans", "weekly_reports")
_LOCAL = """
    CROSS JOIN LATERAL (
        SELECT CASE WHEN EXISTS (
            SELECT 1 FROM pg_catalog.pg_timezone_names AS z WHERE z.name = p.timezone
        ) THEN at_time AT TIME ZONE p.timezone END AS ts
    ) AS l
"""


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
    _create_resolvers()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {_RUNTIME_ROLE};"
    )


def _create_tables() -> None:
    execute_script(
        """
        CREATE TABLE baseline_tests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            exam_id uuid NOT NULL,
            question_ids uuid[] NOT NULL
                CHECK (cardinality(question_ids) BETWEEN 1 AND 200),
            systems jsonb NOT NULL CHECK (jsonb_typeof(systems) = 'object'),
            started_at timestamptz NOT NULL DEFAULT now(),
            submitted_at timestamptz,
            results jsonb CHECK (results IS NULL OR jsonb_typeof(results) = 'array'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, exam_id),
            CHECK ((submitted_at IS NULL) = (results IS NULL)),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, exam_id) REFERENCES exams(tenant_id, id) ON DELETE CASCADE
        );

        CREATE TABLE weekly_reports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            week_start date NOT NULL CHECK (extract(isodow FROM week_start) = 1),
            report_version integer NOT NULL CHECK (report_version >= 1),
            report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
            generated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id, week_start),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE
        );

        CREATE INDEX baseline_tests_user_idx ON baseline_tests (tenant_id, user_id, created_at);
        CREATE INDEX weekly_reports_user_idx ON weekly_reports (tenant_id, user_id, week_start);
        CREATE TRIGGER baseline_tests_touch_updated_at BEFORE UPDATE ON baseline_tests
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
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                ) WITH CHECK (
                    tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
                );
            """
        )
    # Only the resolvers (SECURITY DEFINER, owned by the migrator) read these
    # tables across tenants, and they return ids only.
    for table in _RESOLVER_READS:
        execute_script(
            f"""
            CREATE POLICY {table}_migrator_resolver_read ON {table}
                FOR SELECT TO {_MIGRATOR_ROLE} USING (true);
            """
        )


def _create_resolvers() -> None:
    execute_script(
        f"""
        CREATE FUNCTION app.weekly_reports_due(at_time timestamptz)
        RETURNS TABLE (tenant_id uuid, user_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT p.tenant_id, p.user_id
            FROM public.study_profiles AS p
            {_LOCAL}
            WHERE l.ts >= date_trunc('week', l.ts) + interval '6 hours'
              AND p.created_at < (date_trunc('week', l.ts) AT TIME ZONE p.timezone)
              AND p.exam_date >= (date_trunc('week', l.ts) - interval '7 days')::date
              AND NOT EXISTS (
                  SELECT 1 FROM public.weekly_reports AS r
                  WHERE r.tenant_id = p.tenant_id AND r.user_id = p.user_id
                    AND r.week_start = (date_trunc('week', l.ts) - interval '7 days')::date
              )
        $$;

        CREATE FUNCTION app.study_replans_due(at_time timestamptz, min_version integer)
        RETURNS TABLE (tenant_id uuid, user_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT p.tenant_id, p.user_id
            FROM public.study_profiles AS p
            {_LOCAL}
            WHERE l.ts::time >= time '22:00'
              AND p.exam_date > l.ts::date
              AND NOT EXISTS (
                  SELECT 1 FROM public.study_plans AS s
                  WHERE s.tenant_id = p.tenant_id AND s.user_id = p.user_id
                    AND s.plan_date = l.ts::date + 1 AND s.plan_version >= min_version
              )
        $$;

        REVOKE ALL ON FUNCTION app.weekly_reports_due(timestamptz) FROM PUBLIC;
        REVOKE ALL ON FUNCTION app.study_replans_due(timestamptz, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.weekly_reports_due(timestamptz) TO {_RUNTIME_ROLE};
        GRANT EXECUTE ON FUNCTION app.study_replans_due(timestamptz, integer)
            TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP FUNCTION IF EXISTS app.study_replans_due(timestamptz, integer);
        DROP FUNCTION IF EXISTS app.weekly_reports_due(timestamptz);
        DROP POLICY IF EXISTS study_profiles_migrator_resolver_read ON study_profiles;
        DROP POLICY IF EXISTS study_plans_migrator_resolver_read ON study_plans;
        DROP TABLE IF EXISTS weekly_reports;
        DROP TABLE IF EXISTS baseline_tests;
        """
    )
