"""Tutor depth: attached images and rolling thread memory (ADR 0025).

Expand-only (hard rule 5): one new table and new nullable/defaulted columns;
nothing is dropped, renamed, or rewritten.

* ``tutor_images`` - an image a user attached to a tutor question. The bytes
  live in private object storage under ``tenants/<tenant>/tutor-images/<user>/``
  (a CHECK pins the key to that prefix); the row holds the key, type, size,
  hash, and the cached AI reading. ENABLE + FORCE RLS with the tenant policy,
  and a two-tenant runtime-role proof in evals/checks/test_tutor_depth_live.py.
* ``tutor_messages.image_id`` - the image a user message asked about, bound to
  the same tenant by a composite foreign key; only user messages carry one.
* ``tutor_threads.memory_*`` - the rolling summary of older turns, how many
  messages it covers, and the agent version that wrote it.

Revision ID: 20260926_0017
Revises: 20260926_0014
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0017"
down_revision = "20260926_0015"
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
    _create_images()
    _extend_threads_and_messages()


def _create_images() -> None:
    execute_script(
        f"""
        CREATE TABLE tutor_images (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            storage_key text NOT NULL,
            content_type text NOT NULL
                CHECK (content_type IN ('image/png', 'image/jpeg', 'image/webp')),
            byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 20971520),
            width integer NOT NULL CHECK (width > 0),
            height integer NOT NULL CHECK (height > 0),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
            reading jsonb CHECK (reading IS NULL OR jsonb_typeof(reading) = 'object'),
            reading_version text NOT NULL DEFAULT '' CHECK (length(reading_version) <= 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
            CHECK (storage_key LIKE 'tenants/' || tenant_id::text || '/tutor-images/'
                                    || user_id::text || '/%'),
            CHECK (position('..' in storage_key) = 0)
        );
        CREATE INDEX tutor_images_user_idx ON tutor_images (tenant_id, user_id, created_at);

        ALTER TABLE tutor_images ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tutor_images FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON tutor_images FROM PUBLIC;
        CREATE POLICY tutor_images_tenant_all ON tutor_images
            FOR ALL USING (
                tenant_id = app.current_tenant_id()
                AND tenant_id <> '{_CORE}'::uuid
            ) WITH CHECK (
                tenant_id = app.current_tenant_id()
                AND tenant_id <> '{_CORE}'::uuid
            );
        GRANT SELECT, INSERT, UPDATE, DELETE ON tutor_images TO {_RUNTIME_ROLE};
        """
    )


def _extend_threads_and_messages() -> None:
    execute_script(
        """
        ALTER TABLE tutor_messages ADD COLUMN image_id uuid;
        ALTER TABLE tutor_messages ADD CONSTRAINT tutor_messages_image_fk
            FOREIGN KEY (tenant_id, image_id) REFERENCES tutor_images(tenant_id, id);
        ALTER TABLE tutor_messages ADD CONSTRAINT tutor_messages_image_user_only
            CHECK (image_id IS NULL OR role = 'user');
        CREATE INDEX tutor_messages_image_idx ON tutor_messages (tenant_id, image_id)
            WHERE image_id IS NOT NULL;

        ALTER TABLE tutor_threads
            ADD COLUMN memory_summary text NOT NULL DEFAULT ''
                CHECK (length(memory_summary) <= 4000),
            ADD COLUMN memory_covered integer NOT NULL DEFAULT 0
                CHECK (memory_covered >= 0),
            ADD COLUMN memory_version text NOT NULL DEFAULT ''
                CHECK (length(memory_version) <= 200);
        """
    )


def downgrade() -> None:
    execute_script(
        """
        ALTER TABLE tutor_threads
            DROP COLUMN IF EXISTS memory_version,
            DROP COLUMN IF EXISTS memory_covered,
            DROP COLUMN IF EXISTS memory_summary;
        DROP INDEX IF EXISTS tutor_messages_image_idx;
        ALTER TABLE tutor_messages DROP CONSTRAINT IF EXISTS tutor_messages_image_user_only;
        ALTER TABLE tutor_messages DROP CONSTRAINT IF EXISTS tutor_messages_image_fk;
        ALTER TABLE tutor_messages DROP COLUMN IF EXISTS image_id;
        DROP TABLE IF EXISTS tutor_images;
        """
    )
