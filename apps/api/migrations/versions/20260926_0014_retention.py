"""24-month retention purge finder (ADR 0009, ADR 0020).

Expand-only: adds one narrow SECURITY DEFINER function and two migrator-only
read policies, and no table or column.

* ``app.retention_due_sources(at, default_months)`` returns only
  (tenant_id, source_id, months) for private sources older than their tenant's
  retention period, so the daily beat task can find them without reading any
  tenant's rows; the purge itself runs under that tenant's context. It never
  returns Core scope or Core tenant sources, sources under legal hold, or
  sources of a tenant whose ``settings.retention_months`` is ``0`` (exempt).
  Any other whole number in that setting overrides ``default_months``.

Revision ID: 20260926_0014
Revises: 20260926_0013
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0014"
down_revision = "20260926_0013"
branch_labels = None
depends_on = None

_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"


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

        -- The definer runs as the migrator, which forced RLS also binds; these
        -- read-only policies apply to that role alone, as for users/memberships.
        CREATE POLICY tenants_migrator_retention_read ON tenants
            FOR SELECT TO {_MIGRATOR_ROLE} USING (true);
        CREATE POLICY sources_migrator_retention_read ON sources
            FOR SELECT TO {_MIGRATOR_ROLE} USING (true);

        CREATE FUNCTION app.retention_due_sources(at_time timestamptz, default_months integer)
        RETURNS TABLE (tenant_id uuid, source_id uuid, months integer)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            WITH policy AS (
                SELECT t.id,
                       CASE WHEN (t.settings ->> 'retention_months') ~ '^[0-9]{{1,4}}$'
                            THEN (t.settings ->> 'retention_months')::integer
                            ELSE default_months END AS months
                FROM public.tenants AS t
                WHERE t.kind <> 'core'
            )
            SELECT s.tenant_id, s.id, p.months
            FROM public.sources AS s
            JOIN policy AS p ON p.id = s.tenant_id
            WHERE p.months > 0
              AND s.scope = 'private'
              AND NOT s.legal_hold
              AND s.created_at < at_time - make_interval(months => p.months)
            ORDER BY s.created_at
            LIMIT 500
        $$;
        REVOKE ALL ON FUNCTION app.retention_due_sources(timestamptz, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.retention_due_sources(timestamptz, integer)
            TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP FUNCTION IF EXISTS app.retention_due_sources(timestamptz, integer);
        DROP POLICY IF EXISTS sources_migrator_retention_read ON sources;
        DROP POLICY IF EXISTS tenants_migrator_retention_read ON tenants;
        """
    )
