"""/v1/me and /v1/tenants/switch answer from the caller's membership row (G27)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from uuid import UUID

import pytest
from apps.api.app.api import account
from apps.api.app.main import app
from apps.api.app.security.principal import Principal
from fastapi.testclient import TestClient

USER = UUID("10000000-0000-4000-8000-0000000000a1")
TENANT = UUID("20000000-0000-4000-8000-0000000000a1")
FOREIGN = UUID("20000000-0000-4000-8000-0000000000b2")


class FakeDirectory:
    """Rows as the RLS-bound session would see them: only the caller's tenant."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], dict[str, Any]] = {
            (USER, TENANT): {"id": TENANT, "name": "Synthetic study tenant",
                             "kind": "personal", "role": "student"},
        }
        self.calls: list[tuple[UUID, UUID]] = []

    async def membership(self, user_id: UUID, tenant_id: UUID) -> Mapping[str, Any] | None:
        self.calls.append((user_id, tenant_id))
        return self.rows.get((user_id, tenant_id))


@pytest.fixture
def directory() -> Iterator[FakeDirectory]:
    fake = FakeDirectory()
    app.dependency_overrides[account.principal_context] = lambda: Principal(USER, TENANT)
    app.dependency_overrides[account.get_directory] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def test_me_and_switch_require_a_credential() -> None:
    client = TestClient(app)
    assert client.get("/v1/me").status_code == 401
    assert client.post(f"/v1/tenants/switch?tenant_id={TENANT}").status_code == 401


def test_me_returns_the_membership_tenant_name_and_kind(directory: FakeDirectory) -> None:
    response = TestClient(app).get("/v1/me")
    assert response.status_code == 200
    assert response.json() == {"id": str(TENANT), "name": "Synthetic study tenant",
                               "kind": "personal", "role": "student"}
    assert directory.calls == [(USER, TENANT)]


def test_me_refuses_when_the_membership_row_is_gone(directory: FakeDirectory) -> None:
    directory.rows.clear()
    assert TestClient(app).get("/v1/me").status_code == 403


def test_role_comes_from_the_membership_row(directory: FakeDirectory) -> None:
    directory.rows[(USER, TENANT)]["role"] = "org_admin"
    assert TestClient(app).get("/v1/me").json()["role"] == "org_admin"


def test_switch_to_own_tenant_is_allowed(directory: FakeDirectory) -> None:
    response = TestClient(app).post(f"/v1/tenants/switch?tenant_id={TENANT}")
    assert response.status_code == 200
    assert response.json()["id"] == str(TENANT)
    assert response.json()["name"] == "Synthetic study tenant"


def test_switch_to_a_foreign_tenant_is_refused_without_reading_it(
    directory: FakeDirectory,
) -> None:
    response = TestClient(app).post(f"/v1/tenants/switch?tenant_id={FOREIGN}")
    assert response.status_code == 403
    assert directory.calls == []


def test_switch_is_refused_when_the_own_membership_is_inactive(
    directory: FakeDirectory,
) -> None:
    directory.rows.clear()
    assert TestClient(app).post(f"/v1/tenants/switch?tenant_id={TENANT}").status_code == 403


def test_switch_rejects_a_malformed_tenant_id(directory: FakeDirectory) -> None:
    assert TestClient(app).post("/v1/tenants/switch?tenant_id=not-a-uuid").status_code == 422


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row


class _Session:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.statements.append((str(statement), params))
        return _Result(self.row)


async def test_sql_directory_scopes_by_user_tenant_and_active_rows() -> None:
    session = _Session({"id": TENANT, "name": "T", "kind": "personal", "role": "student"})
    row = await account.SqlTenantDirectory(session).membership(  # type: ignore[arg-type]
        USER, TENANT)
    assert row is not None and row["kind"] == "personal"
    sql, params = session.statements[0]
    assert params == {"user_id": USER, "tenant_id": TENANT}
    for fragment in ("m.user_id = :user_id", "m.tenant_id = :tenant_id", "m.active",
                     "m.deleted_at IS NULL", "t.deleted_at IS NULL"):
        assert fragment in sql
    missing = account.SqlTenantDirectory(_Session(None))  # type: ignore[arg-type]
    assert await missing.membership(USER, TENANT) is None
