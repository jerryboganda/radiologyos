"""Curriculum approvals, exam-blueprint overrides, and node-level mappings (ADR 0023).

Expand-only:

* ``curriculum_mappings.curriculum_node_id`` (nullable) holds the most specific
  curriculum node a mapping names (system, topic, or subtopic); the existing
  ``curriculum_code`` keeps the system so every system-level reader is
  unchanged. NULL on older rows means "system level".
* ``curriculum_reviews`` records the owner's approve/reject decisions on a
  packaged curriculum version, bound to the pack's content hash. Rows are never
  updated; a new decision is a new row.
* ``exam_blueprints`` holds a tenant's overrides of a packaged exam blueprint
  and its approval, bound to the hash of the effective blueprint.

Both tables are tenant-scoped with ENABLE + FORCE RLS (two-tenant proof in
evals/checks/test_curriculum_blueprints_live.py) and are in the data-rights
registry.

Revision ID: 20260926_0015
Revises: 20260926_0014
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0015"
down_revision = "20260926_0014"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("curriculum_reviews", "exam_blueprints")


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

        ALTER TABLE curriculum_mappings ADD COLUMN curriculum_node_id text
            CHECK (curriculum_node_id IS NULL OR length(curriculum_node_id) BETWEEN 1 AND 120);

        CREATE TABLE curriculum_reviews (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            pack_id text NOT NULL CHECK (pack_id ~ '^[a-z0-9_]{{1,60}}$'),
            pack_version text NOT NULL CHECK (length(pack_version) BETWEEN 1 AND 40),
            content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{{64}}$'),
            decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
            notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
            decided_by uuid NOT NULL,
            decided_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, decided_by) REFERENCES users(tenant_id, id)
        );

        CREATE TABLE exam_blueprints (
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            blueprint_id text NOT NULL CHECK (blueprint_id ~ '^[a-z0-9_]{{1,60}}$'),
            overrides jsonb NOT NULL DEFAULT '{{}}'::jsonb
                CHECK (jsonb_typeof(overrides) = 'object'),
            approved boolean NOT NULL DEFAULT false,
            content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{{64}}$'),
            approved_by uuid,
            approved_at timestamptz,
            updated_by uuid NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, blueprint_id),
            CHECK (NOT approved OR (approved_by IS NOT NULL AND approved_at IS NOT NULL
                                    AND content_hash IS NOT NULL)),
            FOREIGN KEY (tenant_id, updated_by) REFERENCES users(tenant_id, id),
            FOREIGN KEY (tenant_id, approved_by) REFERENCES users(tenant_id, id)
        );

        CREATE INDEX curriculum_reviews_pack_idx
            ON curriculum_reviews (tenant_id, pack_id, decided_at DESC);
        CREATE TRIGGER exam_blueprints_touch_updated_at BEFORE UPDATE ON exam_blueprints
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
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
    # Decisions are append-only for the app (DELETE only for account erasure).
    execute_script(
        f"""
        GRANT SELECT, INSERT, DELETE ON curriculum_reviews TO {_RUNTIME_ROLE};
        GRANT SELECT, INSERT, UPDATE, DELETE ON exam_blueprints TO {_RUNTIME_ROLE};
        """
    )


def downgrade() -> None:
    execute_script(
        """
        DROP TABLE IF EXISTS exam_blueprints;
        DROP TABLE IF EXISTS curriculum_reviews;
        ALTER TABLE curriculum_mappings DROP COLUMN IF EXISTS curriculum_node_id;
        """
    )
