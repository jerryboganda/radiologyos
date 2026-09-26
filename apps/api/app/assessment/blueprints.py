"""Tenant blueprint overrides, approval, and blueprint-built papers (RLS; ADR 0023).

The packaged defaults live in ``packages/assessment/blueprints.json``. A tenant
row in ``exam_blueprints`` may override the editable fields; changing an
override clears its approval. Approval is bound to the hash of the effective
blueprint, so a later change to the packaged default also shows as unapproved.
Every override and approval is audited by id only.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from uuid import UUID

from apps.api.app.assessment.question_systems import QUESTION_SYSTEMS
from apps.api.app.library.service import audit
from apps.api.app.security.principal import Principal
from packages.assessment.blueprints import (
    Blueprint,
    blueprint_hash,
    effective,
    minutes_for,
    mix_groups,
    packaged,
    scaled_items,
)
from packages.assessment.paper import PaperCandidate, assemble
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UnknownBlueprint(LookupError):
    pass


def _default(blueprint_id: str) -> Blueprint:
    found = packaged().get(blueprint_id)
    if found is None:
        raise UnknownBlueprint(blueprint_id)
    return found


async def _rows(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = await session.execute(text(
        "SELECT blueprint_id, overrides, approved, content_hash, approved_at, updated_at "
        "FROM exam_blueprints"))
    return {r["blueprint_id"]: dict(r) for r in rows.mappings()}


def _view(default: Blueprint, row: dict[str, Any] | None) -> dict[str, Any]:
    overrides = dict((row or {}).get("overrides") or {})
    current = effective(default, overrides)
    digest = blueprint_hash(current)
    approved = bool(row and row["approved"] and row["content_hash"] == digest)
    return {**current.model_dump(mode="json"), "content_hash": digest,
            "overrides": overrides, "default": default.model_dump(mode="json"),
            "approved": approved, "approved_at": row["approved_at"] if approved and row else None}


async def list_blueprints(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await _rows(session)
    return [_view(bp, rows.get(bp.id)) for bp in packaged().values()]


async def get_blueprint(session: AsyncSession, blueprint_id: str) -> dict[str, Any]:
    return _view(_default(blueprint_id), (await _rows(session)).get(blueprint_id))


async def set_overrides(
    session: AsyncSession, principal: Principal, blueprint_id: str, overrides: dict[str, Any]
) -> dict[str, Any]:
    """Replace the tenant's override (validated); clears any approval."""
    effective(_default(blueprint_id), overrides)  # raises ValueError when invalid
    await session.execute(
        text(
            """
            INSERT INTO exam_blueprints (tenant_id, blueprint_id, overrides, updated_by)
            VALUES (:t, :b, CAST(:o AS jsonb), :u)
            ON CONFLICT (tenant_id, blueprint_id) DO UPDATE SET
                overrides = EXCLUDED.overrides, updated_by = EXCLUDED.updated_by,
                approved = false, content_hash = NULL, approved_by = NULL, approved_at = NULL
            """
        ),
        {"t": principal.tenant_id, "b": blueprint_id, "o": json.dumps(overrides),
         "u": principal.user_id},
    )
    await audit(session, principal, "assessment.blueprint_overridden", "exam_blueprint",
                blueprint_id, {"fields": sorted(overrides)})
    view = await get_blueprint(session, blueprint_id)
    await session.commit()
    return view


async def approve(
    session: AsyncSession, principal: Principal, blueprint_id: str, content_hash: str
) -> dict[str, Any]:
    """Approve the effective blueprint the owner reviewed (hash must match)."""
    current = await get_blueprint(session, blueprint_id)
    if current["content_hash"] != content_hash:
        raise ValueError("the blueprint changed since it was reviewed; reload and approve again")
    await session.execute(
        text(
            """
            INSERT INTO exam_blueprints (tenant_id, blueprint_id, overrides, updated_by,
                                         approved, content_hash, approved_by, approved_at)
            VALUES (:t, :b, CAST(:o AS jsonb), :u, true, :h, :u, now())
            ON CONFLICT (tenant_id, blueprint_id) DO UPDATE SET
                approved = true, content_hash = EXCLUDED.content_hash,
                approved_by = EXCLUDED.approved_by, approved_at = EXCLUDED.approved_at
            """
        ),
        {"t": principal.tenant_id, "b": blueprint_id, "o": json.dumps(current["overrides"]),
         "u": principal.user_id, "h": content_hash},
    )
    await audit(session, principal, "assessment.blueprint_approved", "exam_blueprint",
                blueprint_id, {"content_hash": content_hash})
    view = await get_blueprint(session, blueprint_id)
    await session.commit()
    return view


async def _approved_weights(session: AsyncSession, user_id: UUID, target: str) -> dict[str, float]:
    rows = await session.execute(
        text("SELECT curriculum_code, weight FROM topic_weights WHERE user_id = :u "
             "AND approved AND topic = '' AND exam_target = :target"),
        {"u": user_id, "target": target},
    )
    return {str(r[0]): float(r[1]) for r in rows}


async def _candidates(
    session: AsyncSession, user_id: UUID, types: list[str], target: str, topic: str | None
) -> list[PaperCandidate]:
    rows = await session.execute(
        text(
            QUESTION_SYSTEMS + """
            SELECT q.id, q.type, qsys.curriculum_code, :target = ANY(q.exam_tags) AS tagged
            FROM questions q LEFT JOIN qsys ON qsys.question_id = q.id
            WHERE q.user_id = :u AND q.status = 'active' AND q.type = ANY(:types)
              AND (CAST(:topic AS text) IS NULL OR q.topic ILIKE :topic)
            """  # nosec B608 - constant SQL; all values are bound parameters
        ),
        {"u": user_id, "types": types, "target": target,
         "topic": f"%{topic.replace('%', '').replace('_', ' ')}%" if topic else None},
    )
    return [PaperCandidate(r[0], str(r[1]), r[2], bool(r[3])) for r in rows]


async def build_paper(
    session: AsyncSession, user_id: UUID, config: dict[str, Any]
) -> tuple[list[tuple[UUID, str]], dict[str, Any]]:
    """Pick questions per the blueprint's counts and mix; returns picks and config extras."""
    view = await get_blueprint(session, config["blueprint_id"])
    blueprint = effective(_default(config["blueprint_id"]), view["overrides"])
    counts = scaled_items(blueprint, config.get("blueprint_items"))
    weights = await _approved_weights(session, user_id, blueprint.exam_target)
    candidates = await _candidates(session, user_id, list(counts), blueprint.exam_target,
                                   config.get("topic"))
    picks, report = assemble(candidates, counts, mix_groups(blueprint, weights),
                             secrets.randbits(32))
    extras = {
        "exam_target": blueprint.exam_target, "types": list(counts),
        "count": sum(counts.values()),
        "time_limit_minutes": config.get("time_limit_minutes") or (
            minutes_for(blueprint, sum(counts.values())) if config["mode"] == "exam" else None),
        "blueprint": {"id": blueprint.id, "title": blueprint.title,
                      "content_hash": view["content_hash"], "approved": view["approved"],
                      "unverified": list(blueprint.unverified), "mix_mode": blueprint.mix_mode},
        "scoring": {"negative_marking": blueprint.negative_marking.enabled,
                    "penalty": blueprint.penalty(),
                    "pass_mark_percent": blueprint.pass_mark_percent},
        "mix_report": report,
    }
    return picks, extras
