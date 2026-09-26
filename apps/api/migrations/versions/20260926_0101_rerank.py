"""Rerank budget (ADR 0028): a per-model Voyage ledger total and a rerank alert kind.

Expand-only. Rerank tokens go into the existing ``embedding_usage`` ledger
under their own model name (for example ``rerank-2.5``). Voyage's free tier is
200M tokens *per model*, so:

* ``app.voyage_model_tokens_total(model)`` returns the lifetime total of one
  model across tenants (a single number; no ids, no content), and is what the
  rerank cap checks;
* ``app.embedding_tokens_total()`` is replaced to count embedding models only
  (every model not named ``rerank*``), so rerank calls never eat into the
  embedding cap and vice versa;
* ``ops_alerts.kind`` also accepts ``rerank_budget``.

No new table. Two-tenant runtime-role proof: evals/checks/test_rerank_budget_live.py.

Revision ID: 20260926_0101
Revises: 20260926_0017
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0101"
down_revision = "20260926_0017"
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

        ALTER TABLE ops_alerts DROP CONSTRAINT ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ('embedding_budget', 'rerank_budget'));

        CREATE FUNCTION app.voyage_model_tokens_total(p_model text)
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT coalesce(sum(u.tokens), 0)::bigint FROM public.embedding_usage AS u
            WHERE u.model = p_model
        $$;
        REVOKE ALL ON FUNCTION app.voyage_model_tokens_total(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.voyage_model_tokens_total(text) TO {_RUNTIME_ROLE};

        CREATE OR REPLACE FUNCTION app.embedding_tokens_total()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT coalesce(sum(u.tokens), 0)::bigint FROM public.embedding_usage AS u
            WHERE u.model NOT LIKE 'rerank%'
        $$;
        """
    )


def downgrade() -> None:
    # The kind constraint is restored NOT VALID: rerank rows written meanwhile are
    # invisible to the migrator under FORCE RLS and are left for the data owner.
    execute_script(
        """
        CREATE OR REPLACE FUNCTION app.embedding_tokens_total()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT coalesce(sum(u.tokens), 0)::bigint FROM public.embedding_usage AS u
        $$;
        DROP FUNCTION IF EXISTS app.voyage_model_tokens_total(text);
        ALTER TABLE ops_alerts DROP CONSTRAINT ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ('embedding_budget')) NOT VALID;
        """
    )
