"""Catalog-driven assertions for the live RLS proof (ADR 0022).

The table list is read from ``pg_catalog`` at run time rather than written down,
so a new tenant table is covered by the production proof the moment its
migration is applied. The catalog is also cross-checked against the data-rights
registry, which ``apps/api/tests/test_data_rights.py`` keeps equal to the
migrations, so a table the deployed database lacks (or has extra) fails loudly.

Every write probe runs inside a transaction that is always rolled back, so the
proof is safe to run as the runtime role against the production database.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from apps.worker.app.datarights import registry

DENIED = "42501"
TENANT_TABLES_SQL = """
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       pg_get_userbyid(c.relowner) AS owner
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND (
    c.relname = 'tenants'
    OR EXISTS (
      SELECT 1 FROM pg_attribute AS a
      WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
        AND a.attnum > 0 AND NOT a.attisdropped
    )
  )
ORDER BY c.relname
"""
OWNED_RELATIONS_SQL = """
SELECT count(*) FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'app')
  AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
"""


def quote_ident(name: str) -> str:
    """Quote a catalog identifier; names only ever come from ``pg_class``."""
    return '"' + name.replace('"', '""') + '"'


def registry_tables() -> set[str]:
    return {item.table for item in registry.OWNED} | set(registry.EXEMPT)


async def assert_runtime_role(runtime: Any) -> None:
    """The runtime role has no bypass, no ownership, and no DDL reach."""
    role = await runtime.fetchrow(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
        "FROM pg_roles WHERE rolname = current_user"
    )
    assert role is not None
    assert not any(tuple(role)), "runtime role must be NOSUPERUSER NOBYPASSRLS"
    assert not await runtime.fetchval(
        "SELECT pg_has_role(current_user, 'radbrain_migrator', 'member')"
    )
    assert await runtime.fetchval(OWNED_RELATIONS_SQL) == 0, "runtime role owns a relation"
    for schema in ("public", "app"):
        assert not await runtime.fetchval(
            "SELECT has_schema_privilege(current_user, $1, 'CREATE')", schema
        ), f"runtime role can CREATE in schema {schema}"
    assert not await runtime.fetchval(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
    ), "runtime role can CREATE in the database"


async def assert_catalog_forced(runtime: Any) -> list[str]:
    """Every tenant table has ENABLE + FORCE RLS and matches the repo inventory."""
    rows = await runtime.fetch(TENANT_TABLES_SQL)
    names = [row["relname"] for row in rows]
    assert names, "no tenant tables found; wrong database?"
    assert set(names) == registry_tables(), (
        f"live tenant tables differ from the repo inventory: "
        f"missing={sorted(registry_tables() - set(names))} "
        f"extra={sorted(set(names) - registry_tables())}"
    )
    unforced = [
        row["relname"]
        for row in rows
        if not (row["relrowsecurity"] and row["relforcerowsecurity"])
    ]
    assert not unforced, f"tables without ENABLE + FORCE RLS: {unforced}"
    current = await runtime.fetchval("SELECT current_user")
    owned = [row["relname"] for row in rows if row["owner"] == current]
    assert not owned, f"runtime role owns tenant tables: {owned}"
    return names


async def _visible_rows(runtime: Any, table: str, context: str | None) -> int | str:
    transaction = runtime.transaction()
    await transaction.start()
    try:
        if context is not None:
            await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", context)
        sql = f"SELECT count(*) FROM {quote_ident(table)}"  # nosec B608 - catalog identifier
        return int(await runtime.fetchval(sql))
    except Exception as exc:  # asyncpg.PostgresError; a denial is also blind
        return str(getattr(exc, "sqlstate", "") or type(exc).__name__)
    finally:
        await transaction.rollback()


async def assert_blind_without_context(runtime: Any, tables: list[str]) -> None:
    """No context and a malformed context both see zero rows in every table."""
    assert not await runtime.fetchval("SELECT current_setting('app.tenant_id', true)"), (
        "the runtime session starts with a tenant context already set"
    )
    leaks: dict[str, object] = {}
    for table in tables:
        for context in (None, "not-a-uuid"):
            seen = await _visible_rows(runtime, table, context)
            if seen not in (0, DENIED):
                leaks[f"{table}[{context or 'none'}]"] = seen
    assert not leaks, f"rows visible without a valid tenant context: {leaks}"


async def _insert_outcome(runtime: Any, table: str, context: str | None) -> str:
    column = "id" if table == "tenants" else "tenant_id"
    transaction = runtime.transaction()
    await transaction.start()
    try:
        if context is not None:
            await runtime.execute("SELECT set_config('app.tenant_id', $1, true)", context)
        sql = (
            f"INSERT INTO {quote_ident(table)} ({column}) "  # nosec B608 - catalog identifier
            "VALUES ($1::uuid)"
        )
        await runtime.execute(sql, str(uuid4()))
    except Exception as exc:  # asyncpg.PostgresError
        return str(getattr(exc, "sqlstate", "") or type(exc).__name__)
    finally:
        await transaction.rollback()
    return "inserted"


async def assert_inserts_denied(runtime: Any, tables: list[str]) -> None:
    """Inserting a row for another tenant is refused by RLS in every table.

    Postgres evaluates the RLS ``WITH CHECK`` before NOT NULL and CHECK
    constraints, so a one-column insert is refused with 42501 when the policy
    holds; any other outcome (a constraint error, or success) means the policy
    let the row through.
    """
    failures: dict[str, str] = {}
    for table in tables:
        for context in (None, str(uuid4())):
            outcome = await _insert_outcome(runtime, table, context)
            if outcome != DENIED:
                failures[f"{table}[{'foreign' if context else 'none'}]"] = outcome
    assert not failures, f"foreign-tenant inserts not refused by RLS: {failures}"
