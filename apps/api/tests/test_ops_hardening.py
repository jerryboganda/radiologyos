"""Migration 0104, Keycloak MFA config, IdP session revocation, admin model usage (ADR 0032)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.app.main import app
from apps.worker.app.datarights import idp, registry
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "apps/api/migrations/versions/20260926_0104_ops_hardening.py"
REALM = ROOT / "infra/keycloak/realm.json"
SUBJECT = "5a1c0e6e-0000-4000-8000-00000000abcd"
HEADERS = {"x-user-id": "10000000-0000-4000-8000-000000000001",
           "x-tenant-id": "20000000-0000-4000-8000-000000000001"}


def test_migration_is_expand_only_with_forced_rls_and_no_update_grant() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260926_0104"' in source
    upgrade = source.split("def downgrade")[0]
    assert not re.search(r"DROP (TABLE|COLUMN)|RENAME", upgrade)
    assert "ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY" in upgrade
    assert "GRANT SELECT, INSERT, DELETE ON llm_calls" in upgrade
    assert "UPDATE ON llm_calls" not in upgrade
    assert "'embedding_budget', 'rerank_budget', 'model_usage_limit'" in upgrade
    body = upgrade.split("CREATE TABLE llm_calls (")[1].split("CREATE INDEX")[0]
    pattern = r"^\s+([a-z_]+) (?:uuid|text|integer|numeric|timestamptz)"
    columns = {m.group(1) for m in re.finditer(pattern, body, re.MULTILINE)}
    assert columns == {"id", "tenant_id", "user_id", "request_id", "agent", "route", "backend",
                       "model", "effort", "status", "error_code", "duration_ms", "input_tokens",
                       "output_tokens", "cost_usd", "created_at"}  # no prompt/output/text column


def test_ledger_rows_are_erased_with_the_account() -> None:
    item = registry.owned("llm_calls")
    assert item.erased_by == "direct" and "llm_calls" in registry.DIRECT_DELETE_ORDER


def test_realm_requires_otp_for_admin_roles_and_scopes_the_ops_client() -> None:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    roles = {r["name"]: r for r in realm["roles"]["realm"]}
    for name in ("org_admin", "superadmin"):
        assert roles[name]["composites"] == {"realm": ["mfa_required"]}
    assert "composites" not in roles["student"]
    assert (realm["otpPolicyType"], realm["otpPolicyDigits"]) == ("totp", 6)
    ops = next(c for c in realm["clients"] if c["clientId"] == "radbrain-ops")
    assert ops["secret"] == "" and ops["serviceAccountsEnabled"] is True
    assert not ops["standardFlowEnabled"] and not ops["directAccessGrantsEnabled"]
    account = next(u for u in realm["users"] if u.get("serviceAccountClientId") == "radbrain-ops")
    assert account["clientRoles"] == {"realm-management": ["manage-users"]}


def _mfa_module() -> Any:
    path = ROOT / "infra/ops/keycloak_mfa.py"
    spec = importlib.util.spec_from_file_location("keycloak_mfa", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAdmin:
    """Enough of the Keycloak admin API for the condition/role helpers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.flows: dict[str, list[dict[str, Any]]] = {"sub": []}
        self.composites: dict[str, list[dict[str, Any]]] = {"org_admin": [], "superadmin": []}

    def maybe(self, path: str) -> Any:
        return {"name": "mfa_required"} if path.startswith("/roles/") else None

    def call(self, method: str, path: str, payload: Any = None) -> Any:
        self.calls.append((method, path, payload))
        if method == "GET" and path.endswith("/composites"):
            return self.composites[path.split("/")[2]]
        if method == "GET" and "/executions" in path:
            return self.flows["sub"]
        if method == "POST" and path.endswith("/executions/execution"):
            self.flows["sub"].append({"id": "e1", "providerId": payload["provider"],
                                      "requirement": "DISABLED"})
        return None


def test_mfa_script_adds_role_composites_and_a_role_condition() -> None:
    mfa = _mfa_module()
    admin = FakeAdmin()
    mfa.ensure_role(admin)
    posted = [p for m, p, _ in admin.calls if m == "POST"]
    assert posted == ["/roles/org_admin/composites", "/roles/superadmin/composites"]
    admin.calls.clear()
    mfa.ensure_condition(admin, "sub", "radbrain-otp-mfa-role", negate=False)
    config = next(body for m, p, body in admin.calls if p.endswith("/config"))
    assert config["config"] == {"condUserRole": "mfa_required", "negate": "false"}
    assert any(m == "PUT" and body["requirement"] == "REQUIRED" for m, _, body in admin.calls)


def _transport(status: int, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        return httpx.Response(status)

    return httpx.MockTransport(handler)


def test_idp_sessions_are_revoked_through_the_admin_api() -> None:
    seen: list[httpx.Request] = []
    outcome = asyncio.run(idp.revoke_sessions(
        SUBJECT, "http://keycloak:8080/", "radbrain", "radbrain-ops", "x" * 40,
        transport=_transport(204, seen)))
    assert outcome == "revoked"
    assert seen[1].url.path == f"/admin/realms/radbrain/users/{SUBJECT}/logout"
    assert seen[1].headers["authorization"] == "Bearer synthetic-token"


@pytest.mark.parametrize(("status", "expected"), [(404, "not_found"), (500, "failed")])
def test_idp_revocation_is_best_effort(status: int, expected: str) -> None:
    outcome = asyncio.run(idp.revoke_sessions(SUBJECT, "http://kc", "radbrain", "c", "s",
                                              transport=_transport(status, [])))
    assert outcome == expected


def test_idp_revocation_is_skipped_without_config_or_subject() -> None:
    assert asyncio.run(idp.revoke_sessions(SUBJECT, "", "radbrain", "", "")) == "not_configured"
    assert asyncio.run(idp.revoke_sessions(None, "http://kc", "r", "c", "s")) == "no_subject"


def test_model_usage_is_admin_only() -> None:
    from apps.api.app.api import admin_model_usage

    client = TestClient(app)
    assert client.get("/v1/admin/model-usage").status_code == 401
    app.dependency_overrides[admin_model_usage.tenant_db_session] = lambda: object()
    try:
        assert client.get("/v1/admin/model-usage", headers=HEADERS).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_model_usage_summarises_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.api import admin_model_usage

    row = {"day": "2026-09-26", "agent": "page_parse/v2", "backend": "claude_code", "calls": 3,
           "ok": 1, "errors": 0, "usage_limit": 2, "rejected": 0, "input_tokens": 10,
           "output_tokens": 5, "cost_usd": 0.5, "avg_duration_ms": 900}

    class Result:
        def __init__(self, rows: list[dict[str, Any]], scalar: int = 0) -> None:
            self.rows, self.scalar = rows, scalar

        def mappings(self) -> list[dict[str, Any]]:
            return self.rows

        def scalar_one(self) -> int:
            return self.scalar

    class Session:
        async def execute(self, statement: Any, params: Any = None) -> Result:
            sql = str(statement)
            if "GROUP BY" in sql:
                return Result([row])
            if "ops_alerts" in sql:
                return Result([{"id": UUID(int=1), "level": "amber",
                                "created_at": "2026-09-26T06:00:00Z", "acknowledged_at": None}])
            return Result([], 2)

    app.dependency_overrides[admin_model_usage.tenant_db_session] = lambda: Session()
    try:
        body = TestClient(app).get("/v1/admin/model-usage",
                                   headers={**HEADERS, "x-role": "org_admin"}).json()
    finally:
        app.dependency_overrides.clear()
    assert (body["calls"], body["usage_limit"], body["usage_limit_last_hour"]) == (3, 2, 2)
    assert body["alerts"][0]["level"] == "amber" and body["rows"][0]["agent"] == "page_parse/v2"
