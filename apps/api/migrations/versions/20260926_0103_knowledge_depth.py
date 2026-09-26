"""Knowledge depth: concept notes, reversible merges, conflict verdicts, tables.

Expand-only (hard rule 5): three new tenant tables, new nullable columns, and a
widened step vocabulary; no column is dropped or renamed.

* ``concept_notes``: versioned, cited Synthesis notes per (user, concept),
  keyed by the hash of the claims they were built from.
* ``concept_merges``: Resolver decisions for concept pairs in the 0.80-0.92
  band, with the snapshot that makes an applied merge reversible.
* ``source_tables``: table blocks as structured rows (CSV/HTML) with bbox
  provenance and a tsvector for search.
* ``concepts.merged_into``: a merged concept redirects to its survivor.
* ``knowledge_conflicts.ai_*`` and ``trust``: the Conflict agent's verdict and
  the owner's "trust source A / B / both valid in context" decision.
* ``job_steps.step`` also accepts ``knowledge_depth``.

Each new table has ENABLE + FORCE row-level security and a two-tenant
runtime-role proof in ``evals/checks/test_knowledge_depth_live.py`` (ADR 0030).

Revision ID: 20260926_0103
Revises: 20260926_0017
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0103"
down_revision = "20260926_0104"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = ("concept_notes", "concept_merges", "source_tables")
_STEPS = (
    "'upload_dedupe_scan', 'render_pages', 'parse_layout', 'extract_figures', "
    "'extract_tables', 'chunk', 'embed_index', 'knowledge_extraction', 'ready_notify'"
)


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
    _expand_existing()
    _create_notes()
    _create_merges()
    _create_tables()
    _create_policies()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {_RUNTIME_ROLE};"
    )


def _expand_existing() -> None:
    execute_script(
        f"""
        ALTER TABLE concepts ADD COLUMN IF NOT EXISTS merged_into uuid;
        ALTER TABLE concepts ADD CONSTRAINT concepts_merged_into_fk
            FOREIGN KEY (tenant_id, merged_into) REFERENCES concepts(tenant_id, id)
            ON DELETE SET NULL (merged_into);
        ALTER TABLE concepts ADD CONSTRAINT concepts_merged_into_not_self
            CHECK (merged_into IS NULL OR merged_into <> id);
        CREATE INDEX concepts_merged_into_idx ON concepts (tenant_id, merged_into)
            WHERE merged_into IS NOT NULL;

        ALTER TABLE knowledge_conflicts
            ADD COLUMN IF NOT EXISTS ai_label text
                CHECK (ai_label IS NULL OR ai_label IN ('conflict', 'context', 'same')),
            ADD COLUMN IF NOT EXISTS ai_confidence real
                CHECK (ai_confidence IS NULL OR ai_confidence BETWEEN 0 AND 1),
            ADD COLUMN IF NOT EXISTS ai_rationale text
                CHECK (ai_rationale IS NULL OR length(ai_rationale) <= 1000),
            ADD COLUMN IF NOT EXISTS ai_context text
                CHECK (ai_context IS NULL OR length(ai_context) <= 300),
            ADD COLUMN IF NOT EXISTS ai_cites text[],
            ADD COLUMN IF NOT EXISTS ai_agent_version text
                CHECK (ai_agent_version IS NULL OR length(ai_agent_version) <= 100),
            ADD COLUMN IF NOT EXISTS trust text
                CHECK (trust IS NULL OR trust IN ('a', 'b', 'both'));

        ALTER TABLE job_steps DROP CONSTRAINT IF EXISTS job_steps_step_check,
            ADD CONSTRAINT job_steps_step_check
            CHECK (step IN ({_STEPS}, 'knowledge_depth'));
        """
    )


def _create_notes() -> None:
    execute_script(
        """
        CREATE TABLE concept_notes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            concept_id uuid NOT NULL,
            version integer NOT NULL CHECK (version >= 1),
            claims_hash text NOT NULL CHECK (claims_hash ~ '^[0-9a-f]{64}$'),
            status text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'verified', 'superseded')),
            body jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
            claim_ids uuid[] NOT NULL DEFAULT '{}',
            sentences integer NOT NULL CHECK (sentences >= 1),
            dropped integer NOT NULL DEFAULT 0 CHECK (dropped >= 0),
            agent_version text NOT NULL CHECK (length(agent_version) BETWEEN 1 AND 100),
            pipeline_version integer NOT NULL DEFAULT 1 CHECK (pipeline_version >= 1),
            verified_by uuid,
            verified_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, user_id, concept_id, version),
            UNIQUE (tenant_id, user_id, concept_id, claims_hash, agent_version),
            CHECK (status <> 'verified' OR verified_at IS NOT NULL),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, concept_id) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX concept_notes_owner_idx
            ON concept_notes (tenant_id, user_id, concept_id, version DESC);
        CREATE TRIGGER concept_notes_touch_updated_at BEFORE UPDATE ON concept_notes
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_merges() -> None:
    execute_script(
        """
        CREATE TABLE concept_merges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            concept_a uuid NOT NULL,
            concept_b uuid NOT NULL,
            similarity real NOT NULL CHECK (similarity BETWEEN 0 AND 1),
            decision text NOT NULL CHECK (decision IN ('merge', 'distinct', 'parent_child')),
            confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            rationale text NOT NULL CHECK (length(btrim(rationale)) BETWEEN 1 AND 1000),
            status text NOT NULL CHECK (status IN ('review', 'applied', 'distinct', 'undone')),
            survivor uuid,
            merged uuid,
            snapshot jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(snapshot) = 'object'),
            agent_version text NOT NULL CHECK (length(agent_version) BETWEEN 1 AND 100),
            decided_by uuid,
            applied_at timestamptz,
            undone_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, concept_a, concept_b),
            CHECK (concept_a < concept_b),
            CHECK (survivor IS NULL OR survivor IN (concept_a, concept_b)),
            CHECK (merged IS NULL OR merged IN (concept_a, concept_b)),
            CHECK (status NOT IN ('applied', 'undone')
                   OR (survivor IS NOT NULL AND merged IS NOT NULL AND applied_at IS NOT NULL)),
            CHECK ((status = 'undone') = (undone_at IS NOT NULL)),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, concept_a) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, concept_b) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX concept_merges_status_idx ON concept_merges (tenant_id, user_id, status);
        CREATE TRIGGER concept_merges_touch_updated_at BEFORE UPDATE ON concept_merges
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        """
    )


def _create_tables() -> None:
    execute_script(
        """
        CREATE TABLE source_tables (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            block_no integer NOT NULL CHECK (block_no >= 0),
            bbox real[] NOT NULL CHECK (array_length(bbox, 1) = 4),
            n_rows integer NOT NULL CHECK (n_rows BETWEEN 1 AND 500),
            n_cols integer NOT NULL CHECK (n_cols BETWEEN 1 AND 30),
            header boolean NOT NULL DEFAULT true,
            cells jsonb NOT NULL CHECK (jsonb_typeof(cells) = 'array'),
            csv text NOT NULL,
            html text NOT NULL,
            plain text NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', plain)) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, page_no, block_no),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );
        CREATE INDEX source_tables_page_idx ON source_tables (tenant_id, source_id, page_no);
        CREATE INDEX source_tables_tsv_idx ON source_tables USING gin (tsv);
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
    for table in reversed(TABLES):
        execute_script(f"DROP TABLE IF EXISTS {table};")
    execute_script(
        f"""
        DELETE FROM job_steps WHERE step = 'knowledge_depth';
        ALTER TABLE job_steps DROP CONSTRAINT IF EXISTS job_steps_step_check,
            ADD CONSTRAINT job_steps_step_check CHECK (step IN ({_STEPS}));
        ALTER TABLE knowledge_conflicts DROP COLUMN IF EXISTS trust,
            DROP COLUMN IF EXISTS ai_agent_version, DROP COLUMN IF EXISTS ai_cites,
            DROP COLUMN IF EXISTS ai_context, DROP COLUMN IF EXISTS ai_rationale,
            DROP COLUMN IF EXISTS ai_confidence, DROP COLUMN IF EXISTS ai_label;
        ALTER TABLE concepts DROP CONSTRAINT IF EXISTS concepts_merged_into_not_self,
            DROP CONSTRAINT IF EXISTS concepts_merged_into_fk,
            DROP COLUMN IF EXISTS merged_into;
        """
    )
