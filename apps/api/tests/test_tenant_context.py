from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from apps.api.app import main
from apps.api.app.db.session import (
    current_tenant_id,
    reset_tenant_context,
    set_tenant_context,
    tenant_context,
)
from apps.api.app.security import context as security_context
from apps.api.app.security.principal import Principal
from fastapi import HTTPException


def test_tenant_context_is_scoped_and_restored() -> None:
    tenant_id = UUID("20000000-0000-0000-0000-000000000002")
    assert current_tenant_id() is None
    with tenant_context(tenant_id):
        assert current_tenant_id() == tenant_id
    assert current_tenant_id() is None


def test_nested_tenant_context_restores_parent() -> None:
    parent = UUID("20000000-0000-0000-0000-000000000002")
    child = UUID("30000000-0000-0000-0000-000000000003")
    token = set_tenant_context(parent)
    try:
        with tenant_context(child):
            assert current_tenant_id() == child
        assert current_tenant_id() == parent
    finally:
        reset_tenant_context(token)
    assert current_tenant_id() is None


@pytest.mark.asyncio
async def test_oidc_principal_opens_and_closes_tenant_session(monkeypatch) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_tenant_session(tenant_id: UUID):
        events.append(f"open:{tenant_id}")
        try:
            yield object()
        finally:
            events.append(f"close:{tenant_id}")

    monkeypatch.setattr(security_context, "tenant_session", fake_tenant_session)
    tenant_id = UUID("20000000-0000-0000-0000-000000000002")
    principal = Principal(
        user_id=UUID("10000000-0000-0000-0000-000000000001"),
        tenant_id=tenant_id,
    )
    request = SimpleNamespace(state=SimpleNamespace(requires_tenant_session=True))

    context = main.principal_context(request, principal)
    assert await anext(context) is principal
    with pytest.raises(StopAsyncIteration):
        await anext(context)

    assert events == [f"open:{tenant_id}", f"close:{tenant_id}"]
    assert not hasattr(request.state, "tenant_session")


@pytest.mark.asyncio
async def test_local_principal_opens_a_tenant_database_session(monkeypatch) -> None:
    events: list[str] = []
    tenant_id = UUID("20000000-0000-0000-0000-000000000002")

    @asynccontextmanager
    async def fake_tenant_session(opened_tenant_id: UUID):
        events.append(f"open:{opened_tenant_id}")
        try:
            yield object()
        finally:
            events.append(f"close:{opened_tenant_id}")

    monkeypatch.setattr(security_context, "tenant_session", fake_tenant_session)
    principal = Principal(user_id=UUID("10000000-0000-0000-0000-000000000001"), tenant_id=tenant_id)
    request = SimpleNamespace(state=SimpleNamespace(local_tenant_id=tenant_id))

    context = main.tenant_db_session(request, principal)
    assert await anext(context) is not None
    with pytest.raises(StopAsyncIteration):
        await anext(context)
    assert events == [f"open:{tenant_id}", f"close:{tenant_id}"]


@pytest.mark.asyncio
async def test_tenant_db_session_fails_closed_without_oidc_scope() -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    context = main.tenant_db_session(request, object())
    with pytest.raises(HTTPException) as denied:
        await anext(context)
    assert denied.value.status_code == 500
