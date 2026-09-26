"""Cloze and image cards, exam results review, and grade disputes (ADR 0029).

Expand-only (hard rule 5): new columns with defaults or NULL, one new table, and
two widened checks; nothing is dropped, renamed, or stops being written.

* ``cards.card_type`` (``basic`` default, ``cloze``, ``image``), ``cards.claim_id``
  (the verified claim a cloze card blanks, bound to the same tenant, set NULL if
  the claim is re-extracted away) and ``cards.figure_id`` (the figure an image card
  shows, same tenant, the card goes with the figure). One card per user and claim,
  and per user and figure, by partial unique indexes.
* ``cards.origin`` is widened to also allow ``claim`` and ``figure``: the check is
  replaced in one statement by a strict superset, so every existing row and every
  writer of the previous release stays valid.
* ``exams.item_seconds`` and ``exams.confidence`` (jsonb objects, default ``{}``):
  per-item active seconds and 1-3 confidence, saved with the answers.
* ``grade_disputes``: a user's dispute of one auto-graded point of a submitted
  exam, resolved by the owner/admin. ENABLE + FORCE row-level security, runtime
  grants, a two-tenant runtime-role proof in
  ``evals/checks/test_cards_results_live.py``, and a data-rights registry entry.

Revision ID: 20260926_0102
Revises: 20260926_0017
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0102"
down_revision = "20260926_0101"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("grade_disputes",)


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
    _expand_cards()
    _expand_exams()
    _create_disputes()
    _create_policies()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {_RUNTIME_ROLE};"
    )


def _expand_cards() -> None:
    execute_script(
        """
        ALTER TABLE cards
            ADD COLUMN IF NOT EXISTS card_type text NOT NULL DEFAULT 'basic'
                CHECK (card_type IN ('basic', 'cloze', 'image')),
            ADD COLUMN IF NOT EXISTS claim_id uuid,
            ADD COLUMN IF NOT EXISTS figure_id uuid;

        ALTER TABLE cards
            ADD CONSTRAINT cards_claim_fk FOREIGN KEY (tenant_id, claim_id)
                REFERENCES claims(tenant_id, id) ON DELETE SET NULL (claim_id),
            ADD CONSTRAINT cards_figure_fk FOREIGN KEY (tenant_id, figure_id)
                REFERENCES figures(tenant_id, id) ON DELETE CASCADE,
            ADD CONSTRAINT cards_image_has_figure
                CHECK (card_type <> 'image' OR figure_id IS NOT NULL);

        -- Widen the origin check (a strict superset of the old one).
        ALTER TABLE cards
            DROP CONSTRAINT IF EXISTS cards_origin_check,
            ADD CONSTRAINT cards_origin_check
                CHECK (origin IN ('manual', 'generated', 'weakness', 'claim', 'figure'));

        CREATE UNIQUE INDEX IF NOT EXISTS cards_claim_uidx
            ON cards (tenant_id, user_id, claim_id) WHERE claim_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS cards_figure_uidx
            ON cards (tenant_id, user_id, figure_id) WHERE figure_id IS NOT NULL;
        """
    )


def _expand_exams() -> None:
    execute_script(
        """
        ALTER TABLE exams
            ADD COLUMN IF NOT EXISTS item_seconds jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(item_seconds) = 'object'),
            ADD COLUMN IF NOT EXISTS confidence jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(confidence) = 'object');
        """
    )


def _create_disputes() -> None:
    execute_script(
        """
        CREATE TABLE grade_disputes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            exam_id uuid NOT NULL,
            question_id uuid NOT NULL,
            point_index smallint NOT NULL CHECK (point_index BETWEEN 0 AND 99),
            reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 2000),
            marks double precision NOT NULL CHECK (marks > 0),
            awarded_before double precision NOT NULL CHECK (awarded_before >= 0),
            awarded_after double precision CHECK (awarded_after IS NULL OR awarded_after >= 0),
            status text NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'accepted', 'rejected')),
            resolution_note text NOT NULL DEFAULT ''
                CHECK (length(resolution_note) <= 2000),
            resolved_by uuid,
            resolved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, exam_id, question_id, point_index),
            CHECK ((status = 'open') = (resolved_at IS NULL)),
            CHECK (status <> 'accepted' OR awarded_after IS NOT NULL),
            CHECK (awarded_after IS NULL OR awarded_after <= marks),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, exam_id) REFERENCES exams(tenant_id, id) ON DELETE CASCADE
        );

        CREATE INDEX grade_disputes_queue_idx ON grade_disputes (tenant_id, status, created_at);
        CREATE INDEX grade_disputes_exam_idx ON grade_disputes (tenant_id, exam_id);
        CREATE TRIGGER grade_disputes_touch_updated_at
            BEFORE UPDATE ON grade_disputes
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


def downgrade() -> None:
    execute_script(
        """
        DROP TABLE IF EXISTS grade_disputes;
        ALTER TABLE exams DROP COLUMN IF EXISTS confidence;
        ALTER TABLE exams DROP COLUMN IF EXISTS item_seconds;
        DELETE FROM cards WHERE origin IN ('claim', 'figure') OR card_type <> 'basic';
        DROP INDEX IF EXISTS cards_figure_uidx;
        DROP INDEX IF EXISTS cards_claim_uidx;
        ALTER TABLE cards
            DROP CONSTRAINT IF EXISTS cards_origin_check,
            ADD CONSTRAINT cards_origin_check
                CHECK (origin IN ('manual', 'generated', 'weakness'));
        ALTER TABLE cards DROP CONSTRAINT IF EXISTS cards_image_has_figure;
        ALTER TABLE cards DROP CONSTRAINT IF EXISTS cards_figure_fk;
        ALTER TABLE cards DROP CONSTRAINT IF EXISTS cards_claim_fk;
        ALTER TABLE cards DROP COLUMN IF EXISTS figure_id;
        ALTER TABLE cards DROP COLUMN IF EXISTS claim_id;
        ALTER TABLE cards DROP COLUMN IF EXISTS card_type;
        """
    )
