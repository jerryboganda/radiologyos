"""Owner controls for the library pipeline, from the worker container (ADR 0037).

    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> status
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> pause
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> resume
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> relaunch
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> approve
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> dismiss
    python -m apps.worker.app.ops.pipeline_cli --subject <oidc-subject> clear-quota

``pause`` stops model work between saved units on every worker; ``resume``
lifts it and ``relaunch`` re-queues every unfinished job and knowledge pass
from the saved state (safe to run any time: finished work is skipped).
``relaunch --redo-unchecked-figures`` also re-reads pages whose figures were
described before diagnoses were checked against the source (ADR 0036), and
``--redo-old-knowledge`` replaces claims an older extraction prompt wrote.
``approve`` sends the items GPT-6 Luna and Sol could not answer to Claude Opus
5.5 high; ``dismiss`` closes them without using Claude. Counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from apps.worker.app.ingest import bulk
from apps.worker.app.ingest.db import make_engine, tenant_tx
from apps.worker.app.ops import pipeline_control as control
from packages.models.gateway import load_agent
from packages.pipeline import state
from sqlalchemy import text

UNCHECKED_FIGURES = f"""
    UPDATE source_pages p SET vision_status = 'pending'
    WHERE p.source_id IN ({control.MINE}) AND EXISTS (
        SELECT 1 FROM figures f WHERE f.source_id = p.source_id AND f.page_no = p.page_no
          AND f.image_key IS NOT NULL AND f.impression_origin IS NULL)
"""  # nosec B608 - constant SQL
# Claims and relations written by an older extraction prompt (a test pass) are
# replaced by the current prompt's: its units re-run on the next knowledge pass.
OLD_KNOWLEDGE = [
    f"DELETE FROM {table} WHERE source_id IN ({control.MINE}) "  # nosec B608 - constant SQL
    f"AND agent_version LIKE 'knowledge_extract/%' AND agent_version <> :current"
    for table in ("claims", "concept_edges")
]  # nosec B608 - constant SQL


async def main(args: argparse.Namespace) -> None:
    engine = make_engine()
    try:
        who = await bulk.resolve(engine, args.subject)
        tenant, user = who.tenant_id, who.user_id
        if args.command == "pause":
            state.set_manual(True)
        elif args.command == "resume":
            state.set_manual(False)
        elif args.command == "clear-quota":
            state.clear_quota()
        elif args.command == "approve":
            print(json.dumps(await control.approve(engine, tenant, user)), flush=True)
        elif args.command == "dismiss":
            print(json.dumps({"dismissed": await control.dismiss(engine, tenant, user)}))
        elif args.command == "relaunch":
            if args.redo_unchecked_figures:
                async with tenant_tx(engine, tenant) as session:
                    reset = await session.execute(text(UNCHECKED_FIGURES), {"u": user})
                count = getattr(reset, "rowcount", 0) or 0
                print(f"pages with unchecked figures queued: {count}", flush=True)
            if args.redo_old_knowledge:
                current = load_agent("knowledge_extract").key
                async with tenant_tx(engine, tenant) as session:
                    for sql in OLD_KNOWLEDGE:
                        await session.execute(text(sql), {"u": user, "current": current})
                print(f"older extraction output removed; current is {current}", flush=True)
            state.set_manual(False)
            await bulk.reprocess(engine, who)
            print(f"knowledge passes requeued: "
                  f"{await control.requeue_knowledge(engine, tenant, user)}", flush=True)
        print(json.dumps(await control.status(engine, tenant, user), default=str), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("command", choices=["status", "pause", "resume", "relaunch", "approve",
                                            "dismiss", "clear-quota"])
    parser.add_argument("--redo-unchecked-figures", action="store_true")
    parser.add_argument("--redo-old-knowledge", action="store_true")
    asyncio.run(main(parser.parse_args()))
