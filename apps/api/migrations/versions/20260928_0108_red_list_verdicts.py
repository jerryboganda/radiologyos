"""The owner's verdicts on the red review list (ADR 0041).

Expand-only (hard rule 5): new nullable columns and CHECKs; nothing is dropped
or renamed.

* ``model_escalations.owner_verdict`` - the owner's decision on a red item:
  ``correct`` (keep as it is), ``needs_fix`` (redo or correct it), or ``remove``.
* ``model_escalations.owner_note`` and ``claims.owner_note`` - the owner's own
  words about the item or flagged fact, kept for the follow-up work.
* ``claims.owner_decided_at`` - when the owner kept or rejected a flagged fact.

Revision ID: 20260928_0108
Revises: 20260927_0107
Create Date: 2026-09-28
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260928_0108"
down_revision = "20260927_0107"
branch_labels = None
depends_on = None

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
        ALTER TABLE model_escalations
            ADD COLUMN IF NOT EXISTS owner_verdict text
                CHECK (owner_verdict IN ('correct', 'needs_fix', 'remove')),
            ADD COLUMN IF NOT EXISTS owner_note text
                CHECK (char_length(owner_note) <= 4000);
        ALTER TABLE claims
            ADD COLUMN IF NOT EXISTS owner_note text
                CHECK (char_length(owner_note) <= 4000),
            ADD COLUMN IF NOT EXISTS owner_decided_at timestamptz;
        """
    )


def downgrade() -> None:
    execute_script(
        """
        ALTER TABLE claims DROP COLUMN IF EXISTS owner_decided_at;
        ALTER TABLE claims DROP COLUMN IF EXISTS owner_note;
        ALTER TABLE model_escalations DROP COLUMN IF EXISTS owner_note;
        ALTER TABLE model_escalations DROP COLUMN IF EXISTS owner_verdict;
        """
    )
