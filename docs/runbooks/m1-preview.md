# M1–M7 non-release preview runbook

Status: **Local preview implemented; staging and release acceptance pending**
Scope: synthetic preview routes and workspace UI; not a product or clinical claim
Related: [ADR 0006](../decisions/0006-non-release-preview-mode.md), [`remaining-work.md`](../remaining-work.md), [data handling](data-handling.md)

## Boundary

Preview mode exists so later-slice contracts can be exercised while protected staging
is unavailable. It is enabled only when `APP_ENV` is `dev`, `development`, or `test`
and `PREVIEW_ENABLED=true`. Production, staging, and unknown environments reject the
setting at startup. Preview state is process-local, synthetic, and not RLS evidence.

Never use preview output as clinical guidance, exam validation, model-quality
evidence, billing evidence, deletion evidence, staging acceptance, or release
approval. Do not paste private study material, patient data, DICOM, credentials, or
provider keys into the preview.

## Local operation

1. Copy `.env.example` to `.env`.
2. Set `PREVIEW_ENABLED=true` and keep `APP_ENV=dev`.
3. Start the stack with `make up` or the documented Compose commands.
4. Complete the local development login, then open `/preview`.
5. Use synthetic text only. The workspace labels every surface `Non-release preview`.

The API exposes `/v1/preview/*`; the web server proxies a fixed allowlist of preview
resources through `apps/web/src/lib/server/preview.ts`. The browser never receives
an OIDC access token or an API bearer token.

## Available seams

| Area | Preview routes | Boundary |
| --- | --- | --- |
| M1 | `/v1/preview/sources`, `/pages/{n}`, `/search`, `/jobs/{id}` | Inline text, server-derived object keys, no upload or signed URL |
| M2 | `/concepts`, `/claims`, `/conflicts`, `/sources/{id}/extract` | Deterministic fixtures, no model or Core promotion |
| M3 | `/tutor/ask` | Lexical retrieval, cited answer or explicit no-source response |
| M4 | `/onboarding`, `/plan`, `/today`, `/cards/*`, `/mastery` | Equal synthetic weights; no pass probability |
| M5 | `/questions`, `/practice`, `/attempts`, `/exams/*` | Fixed synthetic SBA, server-side grading, bounded exam state |
| M6 | `/billing/status`, `/editor/*`, `/admin/*`, `/release-audit` | Mock billing and read/role boundaries; no Stripe or deletion |
| M7 | `/export/markdown`, `/local-mode`, `/capabilities` | Markdown fixture, explicitly uncertified mock local mode, and status matrix |

## Verification

Run locally only lightweight checks:

```powershell
python -m ruff check apps packages evals scripts
python -m mypy apps/api/app apps/worker/app
python -m pytest -q apps/api/tests evals/checks/test_scaffolding.py
npm --prefix apps/web run check
npm --prefix apps/web test
python scripts/generate_openapi_types.py
```

Run Compose, browser, database/RLS, integration, security, eval, and performance
checks in GitHub Actions. Preview browser tests must not reuse protected M0 staging
credentials or claim staging evidence.

## Common failures

| Symptom | Response |
| --- | --- |
| Preview routes return 404 | Check `PREVIEW_ENABLED=true` and local `APP_ENV`; do not enable it outside local/test |
| Page shows unavailable | Sign in through the local session and confirm the API is running |
| Cross-tenant preview data appears | Stop, reset local state, and escalate; never share the state directory |
| Tutor says no grounded answer | Expected when no lexical source match exists; do not add an ungrounded fallback |
| Billing/export/local mode looks real | It is a mock seam; release remains blocked |
| Private content appears in a fixture | Stop, remove it, and follow data-handling cleanup |

## Removal before release

Disable `PREVIEW_ENABLED`, remove `/preview` navigation and proxy resources, delete
synthetic preview state, regenerate the contract, and run the protected staging gates
in [`m0-staging-acceptance.md`](m0-staging-acceptance.md). Preview implementation
does not close any A–Z acceptance row.
