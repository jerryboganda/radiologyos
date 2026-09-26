"""Figure impressions record whether the source states them (ADR 0036).

Expand-only (hard rule 5): two new nullable columns on ``figures``; nothing is
dropped, renamed, or rewritten, and existing rows keep NULL ("not checked").

* ``figures.impression_origin`` - ``source`` when the diagnosis is backed by a
  verbatim quote found in the figure's own or neighbouring page text, ``model``
  when it is only the vision model's opinion (shown as "unverified model
  opinion" and never used as evidence for image questions or cards).
* ``figures.source_quote`` - that verbatim quote, for provenance.

``figures`` already has ENABLE + FORCE row-level security with the tenant
policy and table-level grants, which cover the new columns.

Revision ID: 20260926_0105
Revises: 20260926_0103
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0105"
down_revision = "20260926_0103"
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
        ALTER TABLE figures
            ADD COLUMN IF NOT EXISTS impression_origin text
                CHECK (impression_origin IS NULL OR impression_origin IN ('source', 'model')),
            ADD COLUMN IF NOT EXISTS source_quote text;
        """
    )


def downgrade() -> None:
    execute_script(
        """
        ALTER TABLE figures DROP COLUMN IF EXISTS source_quote,
            DROP COLUMN IF EXISTS impression_origin;
        """
    )
