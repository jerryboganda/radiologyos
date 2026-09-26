# radbrain

Source-controlled implementation of the FCPS Radiology Brain OS specification.

The project is a provenance-first, tenant-isolated radiology study platform with a
SvelteKit PWA, FastAPI API, Celery workers, PostgreSQL/pgvector, Redis, and
S3-compatible object storage.

## Development

Requirements:

- Python 3.12+
- Node.js 24 and npm
- Docker Desktop/Engine with Compose v2 (required for the complete stack)

```powershell
Copy-Item .env.example .env
make up
make check
```

The API can be started without Docker; development header identity works only when
`APP_ENV` is `dev`/`test`, and every route needs PostgreSQL for real data:

```powershell
python -m apps.api.app.main
```

`make check` runs the lightweight local checks (ruff, strict mypy, unit tests and the
M1–M7 eval gates, web check and unit tests). Compose, migrations, live RLS proofs, and
the Playwright end-to-end flow (`.github/workflows/e2e.yml`) run only in GitHub
Actions. The in-memory preview surface was removed (ADR 0031).

The local study material under `Radiology Exam Material/` and `Radiology Images/`
is intentionally ignored by Git. It must not be committed or uploaded to public
fixtures. See `docs/runbooks/data-handling.md` before using it for local tests.

See `docs/SPEC.md` and `docs/decisions/` for product and architectural decisions.
