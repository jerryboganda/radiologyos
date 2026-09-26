"""Add the durable library pipeline tables: pages, blocks, figures, chunks.

Expand-only (hard rule 5): new tables and new nullable columns, nothing dropped
or renamed. Every new table is tenant-scoped with ENABLE + FORCE row-level
security and a two-tenant negative proof in evals/checks/test_rls_live_library.py.

Revision ID: 20260926_0004
Revises: 20260925_0003
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0004"
down_revision = "20260925_0003"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("source_pages", "source_blocks", "figures", "chunks")


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

        ALTER TABLE sources ADD COLUMN IF NOT EXISTS original_filename text
            CHECK (original_filename IS NULL OR length(original_filename) <= 500);
        ALTER TABLE sources ADD COLUMN IF NOT EXISTS byte_size bigint
            CHECK (byte_size IS NULL OR byte_size >= 0);
        ALTER TABLE sources ADD COLUMN IF NOT EXISTS mime_type text
            CHECK (mime_type IS NULL OR length(mime_type) <= 200);
        """
    )
    _create_tables()
    _create_policies()
    execute_script(
        f"""
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON source_pages, source_blocks, figures, chunks TO {_RUNTIME_ROLE};
        GRANT DELETE ON sources TO {_RUNTIME_ROLE};
        """
    )


def _create_tables() -> None:
    execute_script(
        """
        CREATE TABLE source_pages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            width real CHECK (width IS NULL OR width > 0),
            height real CHECK (height IS NULL OR height > 0),
            image_key text,
            native_text text NOT NULL DEFAULT '',
            text_origin text NOT NULL DEFAULT 'native'
                CHECK (text_origin IN ('native', 'vision', 'none')),
            vision_status text NOT NULL DEFAULT 'pending'
                CHECK (vision_status IN ('pending', 'done', 'skipped', 'failed')),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, page_no),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE,
            CHECK (image_key IS NULL OR image_key LIKE 'tenants/' || tenant_id::text || '/%')
        );

        CREATE TABLE source_blocks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            block_no integer NOT NULL CHECK (block_no >= 0),
            kind text NOT NULL CHECK (
                kind IN ('heading', 'paragraph', 'list', 'table', 'caption', 'other')
            ),
            text text NOT NULL,
            bbox real[] NOT NULL CHECK (array_length(bbox, 1) = 4),
            origin text NOT NULL CHECK (origin IN ('native', 'vision')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, page_no, block_no),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE TABLE figures (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            figure_no integer NOT NULL CHECK (figure_no >= 0),
            bbox real[] NOT NULL CHECK (array_length(bbox, 1) = 4),
            image_key text,
            caption text NOT NULL DEFAULT '',
            description text NOT NULL DEFAULT '',
            modality text NOT NULL DEFAULT '',
            anatomy text NOT NULL DEFAULT '',
            findings jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(findings) = 'array'),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, page_no, figure_no),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE,
            CHECK (image_key IS NULL OR image_key LIKE 'tenants/' || tenant_id::text || '/%')
        );

        CREATE TABLE chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            chunk_no integer NOT NULL CHECK (chunk_no >= 0),
            page_from integer NOT NULL CHECK (page_from >= 1),
            page_to integer NOT NULL CHECK (page_to >= page_from),
            heading text NOT NULL DEFAULT '',
            text text NOT NULL CHECK (length(text) > 0),
            block_refs jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(block_refs) = 'array'),
            tsv tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(heading, '')), 'A')
                || setweight(to_tsvector('english', text), 'B')
            ) STORED,
            embedding vector(1024),
            embed_model text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, chunk_no),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX source_pages_source_idx ON source_pages (tenant_id, source_id, page_no);
        CREATE INDEX source_pages_vision_idx ON source_pages (tenant_id, vision_status);
        CREATE INDEX source_blocks_page_idx ON source_blocks (tenant_id, source_id, page_no);
        CREATE INDEX figures_source_idx ON figures (tenant_id, source_id, page_no);
        CREATE INDEX chunks_source_idx ON chunks (tenant_id, source_id, chunk_no);
        CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);
        CREATE INDEX chunks_embedding_idx ON chunks
            USING hnsw (embedding vector_cosine_ops);
        CREATE INDEX figures_text_trgm_idx ON figures
            USING gin ((caption || ' ' || description) gin_trgm_ops);

        CREATE TRIGGER source_pages_touch_updated_at
            BEFORE UPDATE ON source_pages
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER figures_touch_updated_at
            BEFORE UPDATE ON figures
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER chunks_touch_updated_at
            BEFORE UPDATE ON chunks
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
                    tenant_id = app.current_tenant_id()
                    AND tenant_id <> '{_CORE}'::uuid
                ) WITH CHECK (
                    tenant_id = app.current_tenant_id()
                    AND tenant_id <> '{_CORE}'::uuid
                );
            """
        )


def downgrade() -> None:
    execute_script(
        f"""
        REVOKE DELETE ON sources FROM {_RUNTIME_ROLE};
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS figures;
        DROP TABLE IF EXISTS source_blocks;
        DROP TABLE IF EXISTS source_pages;
        """
    )
