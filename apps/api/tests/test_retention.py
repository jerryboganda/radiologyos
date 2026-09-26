"""Retention purge (ADR 0009, ADR 0020): off by default, narrow finder, schedule.

The database-backed purge proof runs as the runtime role in
evals/checks/test_retention_live.py; these tests need no services.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from apps.worker.app.celery_app import celery_app
from apps.worker.app.datarights import retention, tasks

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
             / "20260926_0014_retention.py")


def test_mode_defaults_off_and_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETENTION_PURGE_MODE", raising=False)
    assert retention.configured_mode() == "off"
    for raw, expected in (("dry_run", "dry_run"), (" ENFORCE ", "enforce"),
                          ("delete-everything", "off"), ("", "off")):
        monkeypatch.setenv("RETENTION_PURGE_MODE", raw)
        assert retention.configured_mode() == expected


def test_months_default_to_24_and_ignore_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RETENTION_DEFAULT_MONTHS", raising=False)
    assert retention.configured_months() == 24
    for raw, expected in (("36", 36), ("0", 24), ("-3", 24), ("two", 24)):
        monkeypatch.setenv("RETENTION_DEFAULT_MONTHS", raw)
        assert retention.configured_months() == expected


def test_off_task_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> Any:
        raise AssertionError("retention off must not open a database connection")

    monkeypatch.delenv("RETENTION_PURGE_MODE", raising=False)
    monkeypatch.setattr(tasks, "build_data_deps", forbidden)
    assert tasks.retention_purge.run() == {"due": 0, "purged": 0}


def test_sweep_ignores_modes_other_than_dry_run_and_enforce() -> None:
    now = datetime.now(UTC)
    for mode in ("off", "purge", ""):
        assert asyncio.run(retention.sweep(None, now, mode)) == {"due": 0, "purged": 0}  # type: ignore[arg-type]


def test_manual_command_is_dry_run_only() -> None:
    with pytest.raises(SystemExit):
        retention.main(["--mode", "enforce"])


def test_retention_is_scheduled_daily() -> None:
    entry = celery_app.conf.beat_schedule["retention-purge"]
    assert entry == {"task": "radbrain.retention_purge", "schedule": 86400.0}


def test_migration_is_expand_only_with_a_narrow_ids_only_finder() -> None:
    source = MIGRATION.read_text("utf-8")
    assert 'revision = "20260926_0014"' in source
    assert 'down_revision = "20260926_0013"' in source
    upgrade = source.split("def downgrade")[0]
    assert "DROP " not in upgrade and "RENAME" not in upgrade
    assert "RETURNS TABLE (tenant_id uuid, source_id uuid, months integer)" in upgrade
    assert "SECURITY DEFINER" in upgrade and "SET search_path = pg_catalog, pg_temp" in upgrade
    fn = "app.retention_due_sources(timestamptz, integer)"
    assert f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC" in upgrade
    for guard in ("NOT s.legal_hold", "s.scope = 'private'", "t.kind <> 'core'",
                  "p.months > 0", "LIMIT 500"):
        assert guard in upgrade, guard
    for policy in ("tenants_migrator_retention_read", "sources_migrator_retention_read"):
        assert f"CREATE POLICY {policy}" in upgrade
    assert upgrade.count("TO {_MIGRATOR_ROLE} USING (true)") == 2  # read-only, migrator only
