"""Embedding cost controls (ADR 0019): content cache, usage ledger, ops alerts.

Expand-only. ``embedding_cache`` makes each unique text cost Voyage tokens once
per tenant; ``embedding_usage`` is the token ledger behind the 195M hard stop;
``ops_alerts`` records amber/red budget alerts for admins. All three are
tenant-scoped with ENABLE + FORCE RLS (two-tenant proof in
evals/checks/test_embedding_budget_live.py). The free Voyage allowance is per
account, so ``app.embedding_tokens_total()`` sums the ledger across tenants and
returns a single number (no ids, no content).

Revision ID: 20260926_0013
Revises: 20260926_0012
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0013"
down_revision = "20260926_0012"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("embedding_cache", "embedding_usage", "ops_alerts")


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

        CREATE TABLE embedding_cache (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{{64}}$'),
            model text NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
            dimensions integer NOT NULL CHECK (dimensions > 0),
            embedding vector(1024) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, content_sha256, model, dimensions)
        );

        CREATE TABLE embedding_usage (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            day date NOT NULL,
            model text NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
            tokens bigint NOT NULL DEFAULT 0 CHECK (tokens >= 0),
            requests integer NOT NULL DEFAULT 0 CHECK (requests >= 0),
            PRIMARY KEY (tenant_id, day, model)
        );

        CREATE TABLE ops_alerts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            kind text NOT NULL CHECK (kind IN ('embedding_budget')),
            level text NOT NULL CHECK (level IN ('amber', 'red')),
            detail jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            acknowledged_at timestamptz,
            acknowledged_by uuid,
            UNIQUE (tenant_id, kind, level)
        );

        ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_sha256 char(64)
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{{64}}$');
        ALTER TABLE figures ADD COLUMN IF NOT EXISTS content_sha256 char(64)
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{{64}}$');
        ALTER TABLE figures ADD COLUMN IF NOT EXISTS embedding vector(1024);
        ALTER TABLE figures ADD COLUMN IF NOT EXISTS embed_model text;

        CREATE INDEX chunks_content_hash_idx ON chunks (tenant_id, content_sha256);
        CREATE INDEX figures_content_hash_idx ON figures (tenant_id, content_sha256);
        CREATE INDEX figures_embedding_idx ON figures USING hnsw (embedding vector_cosine_ops);
        """
    )
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
    _create_total_function()


def _create_total_function() -> None:
    # The ledger total is read across tenants by a SECURITY DEFINER function
    # owned by the migrator, which is still bound by FORCE RLS; this policy lets
    # it (and only it) read the numeric counters.
    execute_script(
        f"""
        CREATE POLICY embedding_usage_migrator_total_read ON embedding_usage
            FOR SELECT TO {_MIGRATOR_ROLE} USING (true);

        CREATE FUNCTION app.embedding_tokens_total()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT coalesce(sum(u.tokens), 0)::bigint FROM public.embedding_usage AS u
        $$;
        REVOKE ALL ON FUNCTION app.embedding_tokens_total() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.embedding_tokens_total() TO {_RUNTIME_ROLE};

        GRANT SELECT, INSERT, UPDATE, DELETE ON embedding_cache TO {_RUNTIME_ROLE};
        GRANT SELECT, INSERT, UPDATE ON embedding_usage, ops_alerts TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP FUNCTION IF EXISTS app.embedding_tokens_total();
        DROP INDEX IF EXISTS figures_embedding_idx;
        DROP INDEX IF EXISTS figures_content_hash_idx;
        DROP INDEX IF EXISTS chunks_content_hash_idx;
        DROP TABLE IF EXISTS ops_alerts;
        DROP TABLE IF EXISTS embedding_usage;
        DROP TABLE IF EXISTS embedding_cache;
        """
    )
