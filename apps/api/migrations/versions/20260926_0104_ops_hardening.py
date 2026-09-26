"""Ops hardening: the model-call ledger and usage-limit alerts (ADR 0032).

Expand-only (hard rule 5): one new table, one new index set, and a widened
CHECK; nothing is dropped from a column, renamed, or rewritten.

* ``llm_calls`` - one row per model-call attempt made through the gateway:
  tenant, acting user (nullable: worker jobs act for no signed-in user),
  request id, agent key, route, backend, model, effort, outcome, error class,
  duration, and token/cost numbers when the transport reports them. It holds no
  prompt, output, or user text. ENABLE + FORCE RLS with the tenant policy; the
  runtime role may read, insert, and delete (account erasure) but not update.
  Two-tenant runtime-role proof in evals/checks/test_ops_hardening_live.py.
* ``ops_alerts.kind`` - also allows ``model_usage_limit`` (amber alert when
  usage-limit errors spike). Widening a CHECK accepts every existing row.

Revision ID: 20260926_0104
Revises: 20260926_0017
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0104"
down_revision = "20260926_0102"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
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
        """
    )
    _create_ledger()
    _widen_alert_kinds()


def _create_ledger() -> None:
    execute_script(
        f"""
        CREATE TABLE llm_calls (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid,
            request_id uuid,
            agent text NOT NULL CHECK (length(agent) BETWEEN 1 AND 80),
            route text NOT NULL CHECK (route IN ('reason', 'extract', 'classify', 'vision')),
            backend text NOT NULL CHECK (length(backend) BETWEEN 1 AND 40),
            model text NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
            effort text NOT NULL
                CHECK (effort IN ('low', 'medium', 'high', 'xhigh', 'max')),
            status text NOT NULL CHECK (status IN ('ok', 'error', 'usage_limit', 'rejected')),
            error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 80),
            duration_ms integer NOT NULL CHECK (duration_ms >= 0),
            input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
            cost_usd numeric(12, 6) CHECK (cost_usd IS NULL OR cost_usd >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (tenant_id <> '{_CORE}'::uuid)
        );

        CREATE INDEX llm_calls_tenant_created_idx ON llm_calls (tenant_id, created_at DESC);
        CREATE INDEX llm_calls_usage_limit_idx ON llm_calls (tenant_id, created_at)
            WHERE status = 'usage_limit';
        CREATE INDEX llm_calls_user_idx ON llm_calls (tenant_id, user_id)
            WHERE user_id IS NOT NULL;

        ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;
        ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON llm_calls FROM PUBLIC;
        CREATE POLICY llm_calls_tenant_all ON llm_calls
            FOR ALL USING (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            ) WITH CHECK (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            );
        GRANT SELECT, INSERT, DELETE ON llm_calls TO {_RUNTIME_ROLE};
        """
    )


def _widen_alert_kinds() -> None:
    execute_script(
        """
        ALTER TABLE ops_alerts DROP CONSTRAINT IF EXISTS ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ('embedding_budget', 'rerank_budget', 'model_usage_limit'));
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DELETE FROM ops_alerts WHERE kind = 'model_usage_limit';
        ALTER TABLE ops_alerts DROP CONSTRAINT IF EXISTS ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ('embedding_budget', 'rerank_budget')) NOT VALID;
        DROP TABLE IF EXISTS llm_calls;
        """
    )
