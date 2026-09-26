# CONTEXT.md — radbrain current implementation context

Last reviewed: **2026-09-26**
Delivery mode: **personal-first (ADR 0011)** — a real study platform for the owner's
own tenant on the production VPS. Milestone acceptance evidence (ADR 0008) is tracked
separately in [`docs/remaining-work.md`](docs/remaining-work.md).
Canonical requirements: [`docs/SPEC.md`](docs/SPEC.md) plus the ADRs in `docs/decisions/`.
Tracking: [`docs/completion-plan.md`](docs/completion-plan.md) (gap list and phases).

## Purpose

`radbrain` is a provenance-first, tenant-isolated radiology exam-preparation platform
(FCPS-II theory and TOACS, IMM, FRCR). The owner uploads their own material; the
system parses it with Claude Opus 5.5, builds cited search, a grounded tutor, a
knowledge graph with explicit conflicts, an exam-date-driven planner with spaced
repetition, and an assessment engine. Everything a user sees is cited to source,
page, and block, or to an allow-listed web URL.

## What is real (durable, RLS-protected, tested)

| Area | Where | Notes |
| --- | --- | --- |
| Identity | Keycloak (public issuer under `/auth`), `apps/api/app/security/` | OIDC for the browser; the web server calls the API with 60 s signed assertions (ADR 0012) |
| Library | `apps/api/app/library/`, `apps/worker/app/ingest/`, `packages/library/` | upload → render → chunk → embed → ready → Opus page parse + figure cases; resumable jobs |
| Search | `apps/api/app/library/search.py` | tsvector + pgvector, RRF k=60, cited hits and figures |
| Tutor | `packages/tutor/`, `apps/api/app/api/tutor.py` | sources first, allow-listed web research second; code-verified citations plus the semantic grounding judge (ADR 0013) |
| Assessment | `packages/assessment/`, `apps/api/app/assessment/` | SBA/SEQ/TOACS/viva generation, checker gate, exams (ADR 0015) |
| Study | `packages/study/`, `apps/api/app/study/`, `apps/worker/app/study_jobs.py` | FSRS cards, approved-weight planner, baseline test, weekly reports, nightly replan (ADR 0014) |
| Reminders | `packages/notifications/`, `apps/worker/app/reminders.py` | Web Push via VAPID, per-user time and timezone |
| Account | `apps/api/app/api/account.py`, `apps/worker/app/datarights/` | `/v1/me` and `/v1/tenants/switch` answer from the membership row; export ZIP includes an Obsidian-compatible `vault/` (ADR 0031) |
| Models | `packages/models/` | Claude Code headless transport, agent gateway, Voyage embeddings (ADR 0010) |

The M1–M7 in-memory **preview** was removed (ADR 0031); former `/v1/preview/*` paths
answer 404 and `PREVIEW_ENABLED` is ignored. The M1–M7 eval gates
(`evals/checks/test_m*.py`, `test_determinism.py`) run against the durable code with
in-memory repositories and recording sessions; their live PostgreSQL counterparts are
the `*_live.py` proofs. A Playwright E2E workflow (`.github/workflows/e2e.yml`) drives
the real stack in Actions with a seeded synthetic tenant and no model credentials.

## Tenant tables

Every tenant-scoped table has `tenant_id`, ENABLE + FORCE RLS, and a two-tenant
negative proof run as `radbrain_app` in CI (`evals/checks/*_live.py`). Migrations
0001–0014 are expand-only. `evals/checks/test_rls_live.py` also runs against production
and covers every `tenant_id` table from the catalog (ADR 0022).

## Runtime

- Production: shared VPS, compose project `radiologyos` (api, worker with Celery beat,
  web) using the platform Postgres, Redis and MinIO; Keycloak is `radbrain-keycloak`;
  `radiologyos.polytronx.com` is served by nginx-proxy-manager through
  `infra/proxy/radiologyos-manual.conf`. See
  [`docs/runbooks/production-deploy.md`](docs/runbooks/production-deploy.md).
- **Deploys are manual** and need the owner's OK (ADR 0011): push to `main` runs CI and
  builds images only.
- Secrets live only in `/opt/radiologyos/app.env` (mode 600): database, S3, OIDC,
  `WEB_API_SECRET`, `CLAUDE_CODE_OAUTH_TOKEN`, `VOYAGE_API_KEY`, `VAPID_*`.

## Commands

| Command | Purpose |
| --- | --- |
| `python -m ruff check apps packages evals scripts` | lint |
| `python -m mypy apps/api/app apps/worker/app packages` | strict typing |
| `python -m pytest -q apps/api/tests evals/checks` | unit + eval gates (live proofs skip locally) |
| `npm --prefix apps/web run check` / `test` / `build` | web checks |
| `python scripts/generate_openapi_types.py` | refresh `docs/openapi.json` and web types |
| `gh workflow run deploy-production.yml --ref main -f sha=<sha>` | deploy (owner OK only) |

Heavy verification (compose, migrations, live RLS, browser E2E, image builds) runs in
GitHub Actions (ADR 0005).

## Known limitations

- AI parsing and embeddings need `CLAUDE_CODE_OAUTH_TOKEN` and `VOYAGE_API_KEY` in
  `app.env`; without them sources are searchable by keyword only
  ([`docs/runbooks/library.md`](docs/runbooks/library.md)).
- Subscription-based model access covers the owner's own use only (ADR 0010).
- The tutor SSE stream carries stage status only; answer tokens are not streamed yet
  (G8).
- Uploads over 100 MB must use the server-side bulk importer (Cloudflare limit).
- Billing is parked behind `BILLING_ENABLED` (ADR 0011).
