"""Add the knowledge graph, curriculum mappings, and past-paper topic weights.

Expand-only (hard rule 5): new tables only. Every table is tenant-scoped with
ENABLE + FORCE row-level security and a two-tenant runtime-role proof in
evals/checks/test_knowledge_live.py (ADR 0016).

Revision ID: 20260926_0008
Revises: 20260926_0007
Create Date: 2026-09-26
"""

from __future__ import annotations

from apps.api.migrations.sql import execute_script

revision = "20260926_0008"
down_revision = "20260926_0007"
branch_labels = None
depends_on = None

_CORE = "00000000-0000-0000-0000-000000000001"
_RUNTIME_ROLE = "radbrain_app"
_MIGRATOR_ROLE = "radbrain_migrator"
TABLES = (
    "concepts", "claims", "concept_edges", "knowledge_conflicts", "curriculum_mappings",
    "topic_frequencies", "topic_weights", "knowledge_runs",
)
_TARGETS = "'imm', 'fcps2_theory', 'fcps2_toacs', 'frcr', 'unknown'"


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
    _create_graph()
    _create_links()
    _create_mappings()
    _create_weights_and_runs()
    _create_indexes()
    _create_policies()
    execute_script(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {_RUNTIME_ROLE};"
    )


def _create_graph() -> None:
    execute_script(
        """
        CREATE TABLE concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 300),
            normalized_name text NOT NULL CHECK (length(normalized_name) BETWEEN 1 AND 300),
            concept_type text NOT NULL DEFAULT 'other',
            aliases text[] NOT NULL DEFAULT '{}',
            alias_keys text[] NOT NULL DEFAULT '{}',
            curriculum_code text CHECK (curriculum_code IS NULL OR length(curriculum_code) <= 60),
            curriculum_confidence real
                CHECK (curriculum_confidence IS NULL OR curriculum_confidence BETWEEN 0 AND 1),
            summary text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, normalized_name),
            UNIQUE (tenant_id, id)
        );

        CREATE TABLE claims (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            concept_id uuid NOT NULL,
            claim_type text NOT NULL DEFAULT 'other',
            statement text NOT NULL CHECK (length(btrim(statement)) BETWEEN 1 AND 2000),
            evidence_span text NOT NULL CHECK (length(btrim(evidence_span)) >= 1),
            source_id uuid NOT NULL,
            chunk_id uuid REFERENCES chunks(id) ON DELETE SET NULL,
            page_from integer NOT NULL CHECK (page_from >= 1),
            page_to integer NOT NULL CHECK (page_to >= page_from),
            citation jsonb NOT NULL CHECK (jsonb_typeof(citation) = 'object'),
            supporting jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(supporting) = 'array'),
            importance smallint NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
            modality text NOT NULL DEFAULT '',
            agent_version text NOT NULL CHECK (length(agent_version) BETWEEN 1 AND 100),
            verification text NOT NULL DEFAULT 'single_source'
                CHECK (verification IN ('single_source', 'verified')),
            status text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disputed', 'superseded', 'rejected')),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, concept_id) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        """
    )


def _create_links() -> None:
    execute_script(
        """
        CREATE TABLE concept_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            from_concept uuid NOT NULL,
            to_concept uuid NOT NULL,
            relation text NOT NULL CHECK (relation IN (
                'is_a', 'part_of', 'differential_of', 'sign_of', 'causes', 'seen_on',
                'contrasts_with', 'classified_by', 'associated_with'
            )),
            claim_id uuid,
            source_id uuid NOT NULL,
            citation jsonb NOT NULL CHECK (jsonb_typeof(citation) = 'object'),
            agent_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, from_concept, to_concept, relation),
            CHECK (from_concept <> to_concept),
            FOREIGN KEY (tenant_id, from_concept) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, to_concept) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, claim_id) REFERENCES claims(tenant_id, id)
                ON DELETE SET NULL (claim_id),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE TABLE knowledge_conflicts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            concept_id uuid NOT NULL,
            claim_a uuid NOT NULL,
            claim_b uuid NOT NULL,
            kind text NOT NULL
                CHECK (kind IN ('numeric', 'negation', 'opposite_terms', 'model')),
            description text NOT NULL CHECK (length(btrim(description)) BETWEEN 1 AND 1000),
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
            resolution text CHECK (resolution IS NULL OR length(resolution) <= 2000),
            preferred_claim uuid,
            resolved_by uuid,
            resolved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, claim_a, claim_b),
            CHECK (claim_a <> claim_b),
            CHECK ((status = 'resolved') = (resolved_at IS NOT NULL)),
            CHECK (preferred_claim IS NULL OR preferred_claim IN (claim_a, claim_b)),
            FOREIGN KEY (tenant_id, concept_id) REFERENCES concepts(tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, claim_a) REFERENCES claims(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, claim_b) REFERENCES claims(tenant_id, id) ON DELETE CASCADE
        );
        """
    )


def _create_mappings() -> None:
    execute_script(
        f"""
        CREATE TABLE curriculum_mappings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            unit_hash text NOT NULL CHECK (length(unit_hash) BETWEEN 8 AND 64),
            chunk_id uuid REFERENCES chunks(id) ON DELETE SET NULL,
            page_from integer NOT NULL CHECK (page_from >= 1),
            page_to integer NOT NULL CHECK (page_to >= page_from),
            curriculum_code text NOT NULL CHECK (length(curriculum_code) BETWEEN 1 AND 60),
            topic text NOT NULL DEFAULT '' CHECK (length(topic) <= 200),
            confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            status text NOT NULL CHECK (status IN ('accepted', 'review', 'rejected')),
            agent_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, unit_hash, curriculum_code, topic),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        CREATE TABLE topic_frequencies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            source_id uuid NOT NULL,
            page_no integer NOT NULL CHECK (page_no >= 1),
            exam_target text NOT NULL CHECK (exam_target IN ({_TARGETS})),
            paper_label text NOT NULL DEFAULT '' CHECK (length(paper_label) <= 200),
            year integer CHECK (year IS NULL OR year BETWEEN 1990 AND 2100),
            curriculum_code text NOT NULL CHECK (length(curriculum_code) BETWEEN 1 AND 60),
            topic text NOT NULL DEFAULT '' CHECK (length(topic) <= 200),
            count integer NOT NULL CHECK (count >= 1),
            agent_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, page_no, curriculum_code, topic),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );

        """
    )


def _create_weights_and_runs() -> None:
    execute_script(
        f"""
        CREATE TABLE topic_weights (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            user_id uuid NOT NULL,
            exam_target text NOT NULL CHECK (exam_target IN ({_TARGETS}, 'all')),
            curriculum_code text NOT NULL CHECK (length(curriculum_code) BETWEEN 1 AND 60),
            topic text NOT NULL DEFAULT '' CHECK (length(topic) <= 200),
            weight numeric(8, 6) NOT NULL CHECK (weight BETWEEN 0 AND 1),
            basis jsonb NOT NULL CHECK (jsonb_typeof(basis) = 'object'),
            approved boolean NOT NULL DEFAULT false,
            approved_by uuid,
            approved_at timestamptz,
            computed_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id, exam_target, curriculum_code, topic),
            CHECK (approved = (approved_at IS NOT NULL)),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id) ON DELETE CASCADE
        );

        CREATE TABLE knowledge_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_id uuid NOT NULL,
            unit text NOT NULL CHECK (length(unit) BETWEEN 1 AND 100),
            agent_version text NOT NULL CHECK (length(agent_version) BETWEEN 1 AND 100),
            pipeline_version integer NOT NULL CHECK (pipeline_version >= 1),
            status text NOT NULL CHECK (status IN ('succeeded', 'failed', 'skipped')),
            output_ref text CHECK (output_ref IS NULL OR length(output_ref) <= 200),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_id, unit, agent_version, pipeline_version),
            FOREIGN KEY (tenant_id, source_id) REFERENCES sources(tenant_id, id)
                ON DELETE CASCADE
        );
        """
    )


def _create_indexes() -> None:
    execute_script(
        """
        CREATE INDEX concepts_name_trgm_idx ON concepts USING gin (normalized_name gin_trgm_ops);
        CREATE INDEX concepts_alias_keys_idx ON concepts USING gin (alias_keys);
        CREATE INDEX claims_concept_idx ON claims (tenant_id, concept_id);
        CREATE INDEX claims_source_idx ON claims (tenant_id, source_id);
        CREATE INDEX concept_edges_to_idx ON concept_edges (tenant_id, to_concept);
        CREATE INDEX knowledge_conflicts_status_idx ON knowledge_conflicts (tenant_id, status);
        CREATE INDEX curriculum_mappings_status_idx
            ON curriculum_mappings (tenant_id, status, curriculum_code);
        CREATE INDEX topic_frequencies_user_idx
            ON topic_frequencies (tenant_id, user_id, exam_target);
        CREATE INDEX topic_weights_user_idx ON topic_weights (tenant_id, user_id, exam_target);

        CREATE TRIGGER concepts_touch_updated_at BEFORE UPDATE ON concepts
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER claims_touch_updated_at BEFORE UPDATE ON claims
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER knowledge_conflicts_touch_updated_at BEFORE UPDATE ON knowledge_conflicts
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER topic_weights_touch_updated_at BEFORE UPDATE ON topic_weights
            FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
        CREATE TRIGGER knowledge_runs_touch_updated_at BEFORE UPDATE ON knowledge_runs
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
    for table in reversed(TABLES):
        execute_script(f"DROP TABLE IF EXISTS {table};")
