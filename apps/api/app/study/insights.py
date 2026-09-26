"""Progress insights: coverage heatmap, days-remaining projection, calibration bias.

All three are computed in code from the caller's own rows (no model call).
None of them is, or is turned into, a pass probability (CLAUDE.md "Never").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from apps.api.app.study.ports import SessionRepo
from apps.api.app.study.service import local_day, require_profile
from apps.api.app.study.signals import curriculum_nodes, topic_rows
from packages.study import heatmap
from packages.study.calibration import Rated, calibration
from packages.study.projection import WINDOW_DAYS, PacePoint, Topic, project

WINDOW = timedelta(days=90)
NOTICE = ("Coverage, pace and calibration are study signals from your own work. "
          "No pass probability is shown until it has been validated.")


def _pace(rows: list[dict[str, Any]]) -> list[PacePoint]:
    points = []
    for row in rows:
        summary = row.get("summary") or {}
        if "weighted_coverage" in summary:
            points.append(PacePoint(row["session_date"], float(summary["weighted_coverage"]),
                                    int(summary.get("minutes") or 0)))
    return points


async def insights(repo: SessionRepo, user_id: UUID, now: datetime) -> dict[str, Any]:
    profile = await require_profile(repo, user_id)
    rows, weights = await topic_rows(repo, user_id, now, profile)
    nodes = [heatmap.Node(n.code, n.parent_code, n.level, n.title) for n in curriculum_nodes()]
    stats = {
        str(r["curriculum_code"]): heatmap.CodeStats(
            int(r["material"]), int(r["studied"]), float(r["score"]), float(r["max_score"]))
        for r in await repo.coverage_stats(user_id, now - WINDOW)
    }
    systems = [heatmap.SystemMastery(r.node.code, r.mastery.score, r.mastery.band,
                                     r.mastery.coverage, r.weight) for r in rows]
    today = local_day(profile, now)
    history = _pace(await repo.completed_sessions(user_id, today - timedelta(days=WINDOW_DAYS)))
    topics = [Topic(r.weight, r.mastery.coverage) for r in rows]
    rated = [Rated(int(a["confidence"]), a["score"] / a["max_score"] if a["max_score"] else 0.0)
             for a in await repo.rated_attempts(user_id, now - WINDOW)]
    await repo.commit()
    return {
        "heatmap": heatmap.build(nodes, stats, systems),
        "projection": project(today, profile["exam_date"], topics, history),
        "calibration": calibration(rated),
        "weight_policy": weights.policy,
        "notice": NOTICE,
    }
