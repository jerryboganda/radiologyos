from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import yaml
from apps.worker.app.job_id import IngestStep, JobId
from evals.contracts import load_eval_fixtures
from packages.curriculum.contracts import load_curriculum_pack
from packages.models.routing import RouteName, load_model_routing_config, require_mock_routes
from packages.prompts.contracts import load_prompt

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "infra" / "compose" / "production.yml"
DOCKERFILE = ROOT / "infra" / "python" / "Dockerfile"
MIGRATIONS = (
    ROOT / "apps" / "api" / "migrations" / "versions" / "20260924_0001_m0_foundation.py",
    ROOT / "apps" / "api" / "migrations" / "versions" / "20260924_0002_m0_rls.py",
    ROOT / "apps" / "api" / "migrations" / "versions" / "20260925_0003_preview_hardening.py",
)
MODEL_CONFIG = ROOT / "packages" / "models" / "models.yaml"
CURRICULUM = ROOT / "packages" / "curriculum" / "fcps2_radiology.json"
EVAL_FIXTURE = ROOT / "evals" / "fixtures" / "synthetic_smoke_v1.json"
PROMPT_ROOT = ROOT / "packages" / "prompts"


OIDC_WORKFLOW = ROOT / ".github" / "workflows" / "verify-production-oidc.yml"
RLS_WORKFLOW = ROOT / ".github" / "workflows" / "verify-production-rls.yml"
REMAINING_WORK = ROOT / "docs" / "remaining-work.md"
PREVIEW_ADR = ROOT / "docs" / "decisions" / "0006-non-release-preview-mode.md"
ENV_EXAMPLE = ROOT / ".env.example"
PREVIEW_RUNBOOK = ROOT / "docs" / "runbooks" / "m1-preview.md"


def test_compute_policy_and_production_verification_are_fail_closed() -> None:
    workflow = OIDC_WORKFLOW.read_text(encoding="utf-8")
    rls_workflow = RLS_WORKFLOW.read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "workflow_dispatch:" in rls_workflow
    assert "environment: production" in rls_workflow
    assert "RADBRAIN_RLS_ADMIN_DATABASE_URL" in rls_workflow
    assert "RADBRAIN_RLS_RUNTIME_DATABASE_URL" in rls_workflow
    assert "RADBRAIN_RLS_REQUIRED" in rls_workflow
    assert "permissions:" in rls_workflow
    assert "evals/checks/test_rls_live.py" in rls_workflow
    assert "upload-artifact" not in rls_workflow
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "gh run watch" in makefile
    assert "verify-production-rls.yml" in makefile
    assert "rls: ci" not in makefile
    assert "security-scan: ci" in makefile
    assert "upload-artifact" not in workflow
    assert "VPS_SSH_HOST" in workflow
    assert "verify-oidc.py" in workflow
    assert "GitHub Actions" in agents and "GitHub Actions" in claude
    assert "Non-release preview exception" in agents
    assert "Non-release preview exception" in claude

    goal = REMAINING_WORK.read_text(encoding="utf-8")
    headings = (
        "## Objective",
        "## A–Z execution queue",
        "## Definition of done",
        "## Immediate pursuit",
    )
    for heading in headings:
        assert heading in goal
    for slice_name in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        assert f"| {slice_name} |" in goal
    assert "M0 is not accepted" in goal
    assert "No M1–M7 feature has been accepted" in goal


def test_preview_mode_is_explicitly_non_release() -> None:
    adr = PREVIEW_ADR.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    runbook = PREVIEW_RUNBOOK.read_text(encoding="utf-8")
    main = (ROOT / "apps" / "api" / "app" / "api" / "preview.py").read_text(encoding="utf-8")
    production = PRODUCTION_COMPOSE.read_text(encoding="utf-8")

    assert "non-release preview" in adr
    assert "does not supersede" in adr
    assert "PREVIEW_ENABLED=true" in env_example
    assert "Non-release preview" in runbook
    assert "preview: non-release" in main
    assert 'PREVIEW_ENABLED: "false"' in production


def test_compose_runs_real_m0_processes_with_separate_migrator_role() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    production = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "  migrate:" in compose
    assert "  api:" in compose
    assert "  worker:" in compose
    assert "DATABASE_MIGRATOR_URL" in compose
    assert "DATABASE_MIGRATOR_URL" not in compose.split("  api:", 1)[1].split("  worker:", 1)[0]
    assert "DATABASE_MIGRATOR_URL" not in compose.split("  worker:", 1)[1].split("  web:", 1)[0]
    assert "  storage:" in compose
    assert "rustfs/rustfs:1.0.0" in compose
    assert "playwright" not in (ROOT / "apps" / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert "RUSTFS_ACCESS_KEY" in compose
    assert "http://minio:9000" not in compose
    assert "  minio:" not in compose
    assert "uvicorn" in dockerfile
    assert "celery" in compose
    assert "service_completed_successfully" in compose
    migration = (
        ROOT / "apps" / "api" / "migrations" / "versions" / "20260924_0002_m0_rls.py"
    ).read_text(encoding="utf-8")
    assert "pg_auth_members" in migration
    assert "pg_has_role" not in migration
    assert "RAISE EXCEPTION (" not in migration
    assert "REVOKE ALL ON app.current_tenant_id()" not in migration
    assert "REVOKE ALL ON app.touch_updated_at()" not in migration
    assert "RADBRAIN_MIGRATOR_IMAGE" in production
    assert "RADBRAIN_API_IMAGE" in production
    assert "RADBRAIN_WORKER_IMAGE" in production
    assert "RADBRAIN_STORAGE_IMAGE" in production
    assert "RADBRAIN_WEB_IMAGE" in production
    assert production.count("build: !reset null") == 5
    assert not (ROOT / "infra" / "api" / "placeholder.py").exists()


def test_migration_defines_rls_and_role_separation() -> None:
    sql = "\n".join(path.read_text(encoding="utf-8") for path in MIGRATIONS)
    tenant_tables = (
        "tenants",
        "users",
        "memberships",
        "sources",
        "jobs",
        "job_steps",
        "audit_log",
    )
    for table in tenant_tables:
        assert f"CREATE TABLE {table}" in sql
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE FUNCTION app.current_tenant_id()" in sql
    assert "current_setting('app.tenant_id', true)" in sql
    assert "_MIGRATOR_ROLE = \"radbrain_migrator\"" in sql
    assert "_RUNTIME_ROLE = \"radbrain_app\"" in sql
    assert "rolbypassrls" in sql
    assert "REVOKE ALL ON FUNCTION app.resolve_memberships(text) FROM PUBLIC" in sql
    assert "GRANT EXECUTE ON FUNCTION app.resolve_memberships(text)" in sql
    assert "RETURNS TABLE (user_id uuid, tenant_id uuid, role text)" in sql
    assert "REVOKE UPDATE ON tenants, users, memberships" in sql
    assert "GRANT UPDATE (title, page_count, status) ON sources" in sql
    assert "rights_status IN ('authored', 'licensed')" in sql
    assert "deleted_at IS NULL" in sql
    assert "jobs(tenant_id, id, entity_id, pipeline_version)" in sql
    assert "GRANT UPDATE, DELETE ON audit_log" not in sql


def test_model_routes_follow_adr_0010() -> None:
    config = load_model_routing_config(MODEL_CONFIG)

    assert set(config.routes) == set(RouteName)
    assert config.default_backend == "claude_code"
    assert config.provider_gate.status == "approved"
    assert config.provider_gate.approved_by_adr
    assert (ROOT / config.provider_gate.approved_by_adr).is_file()
    assert config.allow_ungrounded_default is False
    for route in config.routes.values():
        assert route.fallbacks == ()
        for target in route.targets:
            assert target.backend == "claude_code"
            assert target.model == "claude-opus-5-5"
            assert target.effort == "high"
            # The subscription token is inherited from the environment, never
            # named or stored in configuration.
            assert target.api_key_env is None
    embeddings = config.embeddings
    assert embeddings is not None
    assert embeddings.dimensions == 1024
    # ADR 0019: every embedding uses voyage-4-large inside the free quota.
    assert (embeddings.document.backend, embeddings.document.model) == ("voyage", "voyage-4-large")
    # Owner override (2026-09-26): queries also use the paid best model, metered.
    assert (embeddings.query.backend, embeddings.query.model) == ("voyage", "voyage-4-large")
    assert embeddings.budget.hard_cap_tokens == 195_000_000
    assert embeddings.budget.warn_tokens == 150_000_000


def test_mock_gate_still_rejects_network_capable_targets() -> None:
    config = load_model_routing_config(MODEL_CONFIG)
    with pytest.raises(ValueError, match="mock-only"):
        require_mock_routes(config)


@pytest.mark.parametrize("route", list(RouteName))
def test_every_route_has_a_versioned_prompt(route: RouteName) -> None:
    prompt_path = PROMPT_ROOT / route.value / "v1.yaml"
    prompt = load_prompt(prompt_path)

    assert prompt.agent == route.value
    assert prompt.route == route
    assert prompt.status == "placeholder"
    assert prompt.safety.allow_ungrounded is False
    assert prompt.safety.source_text_is_data is True
    assert prompt.fixture == "evals/fixtures/synthetic_smoke_v1.json"


def test_placeholder_prompts_are_valid_and_reference_fixture() -> None:
    prompt_paths = sorted(PROMPT_ROOT.glob("*/v*.yaml"))

    assert prompt_paths
    for path in prompt_paths:
        prompt = load_prompt(path)
        assert path.parent.name == prompt.agent
        assert path.name == f"v{prompt.version}.yaml"
        assert (ROOT / "packages" / "prompts" / prompt.output_schema).is_file()


def test_curriculum_is_an_explicit_unvalidated_placeholder() -> None:
    pack = load_curriculum_pack(CURRICULUM)

    assert pack.status == "placeholder_unvalidated"
    assert pack.exam_blueprint is None
    assert len(pack.nodes) == 17
    assert all(node.exam_weight is None for node in pack.nodes)


def test_eval_fixture_is_synthetic_and_links_existing_prompts() -> None:
    fixture = load_eval_fixtures(EVAL_FIXTURE)

    assert fixture.schema_version == 1
    assert fixture.status == "placeholder"
    assert fixture.data_class == "synthetic"
    assert fixture.cases
    for case in fixture.cases:
        prompt_path = ROOT / "packages" / "prompts" / case.prompt
        assert prompt_path.is_file()
        assert case.tenant_id


def test_job_id_is_stable_and_includes_pipeline_version() -> None:
    tenant_id = UUID("20000000-0000-0000-0000-000000000002")
    entity_id = UUID("40000000-0000-0000-0000-000000000004")
    job_id = JobId.from_parts(tenant_id, entity_id, IngestStep.KNOWLEDGE_EXTRACTION, 7)

    assert job_id.tenant_id == tenant_id
    assert job_id.entity_id == entity_id
    assert job_id.step is IngestStep.KNOWLEDGE_EXTRACTION
    assert job_id.pipeline_version == 7
    assert str(job_id) == (
        "20000000-0000-0000-0000-000000000002:"
        "40000000-0000-0000-0000-000000000004:"
        "knowledge_extraction:v7"
    )
    assert JobId.from_key(str(job_id)) == job_id


def test_production_uses_unique_internal_hostnames() -> None:
    """Bare service names collide with other projects on the shared networks."""
    platform = (ROOT / "infra" / "compose" / "platform.yml").read_text(encoding="utf-8")
    assert "http://api:" not in platform
    assert "http://keycloak:" not in platform
    assert "API_INTERNAL_URL: http://radbrain-api:8000" in platform


def test_embedder_is_private_to_the_project_network() -> None:
    """ADR 0019: reachable only by a unique alias on the project network, never ingress."""
    workflows = ROOT / ".github" / "workflows"
    platform_file = ROOT / "infra" / "compose" / "platform.yml"
    alias = {"default": {"aliases": ["radbrain-embedder"]}}
    for compose_file in (platform_file, COMPOSE):
        services = yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"]
        embedder = services["embedder"]
        assert embedder["networks"] == alias
        assert embedder["cpus"] and embedder["mem_limit"]
        assert "ports" not in embedder
        assert services["api"]["environment"]["EMBEDDER_URL"] == "http://radbrain-embedder:8080"
        # Optional dependency: the API must start (lexical search) without it.
        assert "embedder" not in services["api"].get("depends_on", {})
        if compose_file == platform_file:
            assert embedder["image"].startswith("${RADBRAIN_EMBEDDER_IMAGE:?")
    assert "radiologyos-embedder" in (workflows / "build-images.yml").read_text(encoding="utf-8")
    deploy = (workflows / "deploy-production.yml").read_text(encoding="utf-8")
    assert "RADBRAIN_EMBEDDER_IMAGE=%s" in deploy
    assert "/^RADBRAIN_EMBEDDER_IMAGE=/d" in deploy
