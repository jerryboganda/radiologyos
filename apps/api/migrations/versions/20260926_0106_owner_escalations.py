"""Owner escalations, quota alerts, and flagged claims (ADR 0037).

Expand-only (hard rule 5): one new tenant table, one new nullable column, and
two widened CHECKs; nothing is dropped, renamed, or rewritten.

* ``model_escalations`` - items (page, figure page, knowledge unit) that GPT-6
  Luna and Sol could not answer well, waiting for the owner's batch approval
  of the Claude Opus step ("collect & ask"). Ids, agent names, and fixed
  reason strings only - never source text. ENABLE + FORCE RLS with the tenant
  policy; two-tenant runtime-role proof in evals/checks/test_escalations_live.py.
* ``ops_alerts.kind`` - also ``chatgpt_quota`` (pipeline paused on the ChatGPT
  usage window) and ``owner_approval`` (items waiting for approval).
* ``claims.doubt`` and ``claims.status = 'flagged'`` - a claim whose source
  statement contradicts standard teaching (e.g. a wrong bone named) is kept
  for the owner's review and never used as evidence while flagged.

Revision ID: 20260926_0106
Revises: 20260926_0105
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0106"
down_revision = "20260926_0105"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
_KINDS = "'embedding_budget', 'rerank_budget', 'model_usage_limit'"
_STATUSES = "'active', 'disputed', 'superseded', 'rejected'"


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
    _create_escalations()
    execute_script(
        f"""
        ALTER TABLE ops_alerts DROP CONSTRAINT IF EXISTS ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ({_KINDS}, 'chatgpt_quota', 'owner_approval'));
        ALTER TABLE claims ADD COLUMN IF NOT EXISTS doubt text
            CHECK (doubt IS NULL OR length(doubt) <= 500);
        ALTER TABLE claims DROP CONSTRAINT IF EXISTS claims_status_check;
        ALTER TABLE claims ADD CONSTRAINT claims_status_check
            CHECK (status IN ({_STATUSES}, 'flagged'));
        """
    )


def _create_escalations() -> None:
    execute_script(
        f"""
        CREATE TABLE model_escalations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            agent text NOT NULL CHECK (length(agent) BETWEEN 1 AND 80),
            unit text NOT NULL CHECK (length(unit) BETWEEN 1 AND 120),
            reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 80),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'done', 'dismissed')),
            created_at timestamptz NOT NULL DEFAULT now(),
            resolved_at timestamptz,
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE,
            UNIQUE (tenant_id, source_id, agent, unit),
            CHECK (tenant_id <> '{_CORE}'::uuid)
        );
        CREATE INDEX model_escalations_status_idx
            ON model_escalations (tenant_id, status, created_at);

        ALTER TABLE model_escalations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE model_escalations FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON model_escalations FROM PUBLIC;
        CREATE POLICY model_escalations_tenant_all ON model_escalations
            FOR ALL USING (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            ) WITH CHECK (
                tenant_id = app.current_tenant_id() AND tenant_id <> '{_CORE}'::uuid
            );
        GRANT SELECT, INSERT, UPDATE, DELETE ON model_escalations TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        f"""
        DROP TABLE IF EXISTS model_escalations;
        DELETE FROM ops_alerts WHERE kind IN ('chatgpt_quota', 'owner_approval');
        ALTER TABLE ops_alerts DROP CONSTRAINT IF EXISTS ops_alerts_kind_check;
        ALTER TABLE ops_alerts ADD CONSTRAINT ops_alerts_kind_check
            CHECK (kind IN ({_KINDS})) NOT VALID;
        UPDATE claims SET status = 'disputed' WHERE status = 'flagged';
        ALTER TABLE claims DROP CONSTRAINT IF EXISTS claims_status_check;
        ALTER TABLE claims ADD CONSTRAINT claims_status_check
            CHECK (status IN ({_STATUSES}));
        ALTER TABLE claims DROP COLUMN IF EXISTS doubt;
        """
    )
