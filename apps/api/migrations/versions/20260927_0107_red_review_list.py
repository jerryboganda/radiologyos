"""The owner's red review list (ADR 0038): two more escalation statuses.

Expand-only (hard rule 5): a widened CHECK; nothing is dropped or renamed.

* ``review``   - the item's final answer was kept although it fell short of the
  quality bar (no stronger model was left), or every model failed it. It is
  shown to the owner in red, marked with a danger sign, until reviewed.
* ``reviewed`` - the owner has looked at it.

Revision ID: 20260927_0107
Revises: 20260926_0106
Create Date: 2026-09-27
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260927_0107"
down_revision = "20260926_0106"
branch_labels = None
depends_on = None

_MIGRATOR_ROLE = "radbrain_migrator"
_STATUSES = "'pending', 'approved', 'done', 'dismissed'"


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
        ALTER TABLE model_escalations DROP CONSTRAINT IF EXISTS model_escalations_status_check;
        ALTER TABLE model_escalations ADD CONSTRAINT model_escalations_status_check
            CHECK (status IN ({_STATUSES}, 'review', 'reviewed'));
        CREATE INDEX IF NOT EXISTS model_escalations_review_idx
            ON model_escalations (tenant_id, created_at) WHERE status = 'review';
        """
    )


def downgrade() -> None:
    execute_script(
        f"""
        DROP INDEX IF EXISTS model_escalations_review_idx;
        UPDATE model_escalations SET status = 'done' WHERE status IN ('review', 'reviewed');
        ALTER TABLE model_escalations DROP CONSTRAINT IF EXISTS model_escalations_status_check;
        ALTER TABLE model_escalations ADD CONSTRAINT model_escalations_status_check
            CHECK (status IN ({_STATUSES}));
        """
    )
