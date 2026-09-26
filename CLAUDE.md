# CLAUDE.md — radbrain

## Read first

- [`docs/SPEC.md`](docs/SPEC.md) is the working source of truth and incorporates
  the supplied implementation specification by reference.
- [`CONTEXT.md`](CONTEXT.md) describes the current scaffold; do not confuse a
  target requirement with implemented behavior.
- Read the relevant file under `docs/runbooks/` and `docs/decisions/` before
  operational, security, data, or model changes.
- Work M0 through M7 in order. Do not start the next milestone before the current
  milestone passes its authoritative exit evidence under ADR 0008.
- Record every non-trivial architectural or policy choice as a one-paragraph ADR
  in `docs/decisions/NNNN-title.md`.

## Stack — do not substitute

- `apps/api`: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic;
  Ruff, strict mypy, pytest. Integration/RLS tests must use the app database role.
- `apps/worker`: Celery 5 on Redis; every task is idempotent on entity, step, and
  `PIPELINE_VERSION`, with visible resumable step status.
- `apps/web`: SvelteKit 2, TypeScript, Tailwind; run `make types` to generate API
  contracts and keep `svelte-check` clean.
- Data: PostgreSQL 16 with pgvector, tsvector, and RLS; private S3-compatible
  object storage; Redis.
- Models: call only through the named routes `reason`, `extract`, `classify`, and
  `vision` (ADR 0010: Claude Opus 5.5 via the owner's subscription; Voyage AI for
  embeddings). Concrete names live in `packages/models/models.yaml`, never inline
  in application code.

## Deploy rule (ADR 0011)

Commit and push to `main` freely. Never dispatch `deploy-production.yml`, and never
change it back to an automatic trigger, without the owner's explicit OK for that
deploy.

## Preview surface retired

The in-memory non-release preview (ADR 0006) was removed by ADR 0031; all features
are durable, RLS-protected implementations. Synthetic or mock data is still the
rule for tests, and a test pass is still never release evidence (ADR 0008/0022).

## Hard rules

1. Every tenant-scoped table ships with a `tenant_id`, RLS policies, and a
   two-tenant negative test that runs as the non-privileged app role.
2. Every model call has a route name, Pydantic output schema, versioned prompt
   under `packages/prompts/<agent>/vN.yaml`, and eval fixture. No inline prompts.
3. Every claim, card, question, and tutor sentence carries a citation. Any path
   that can emit uncited text runs the grounding judge.
4. Never log source text, embeddings, or prompts containing user content. Log
   stable IDs and hashes only, with secrets and personal data excluded.
5. Migrations are expand-and-contract; never drop or rename a column in the same
   release that stops writing it.
6. Secrets come from the environment or a secret manager. Browser auth tokens stay
   out of localStorage; provider keys never reach the browser.
7. No cross-tenant caching. Cache keys begin with `tenant_id` unless an explicit,
   reviewed Core-scope policy permits sharing.
8. No LangChain, LlamaIndex, Haystack, Obsidian, or Second Brain OS dependency.
   Keep retrieval explicit and tested.
9. Keep source files and documents under 400 lines and functions under 60 lines.
   Prefer targeted edits; never rewrite a file to change one function.
10. Use Conventional Commits, `feature/<milestone>-<slug>` branches, and one
    feature per pull request.

Additional non-negotiables: provenance resolves to source/page/block/bounding box;
figures are first-class; source conflicts are explicit; long operations are
resumable; and personal uploads are never redistributed.

## Loop for every feature

```text
plan -> read spec/context -> write tests for core/security behavior -> implement
     -> run lightweight local checks -> dispatch compute targets with `make ci`
     -> run `make types` and review the generated diff
     -> run integration/eval targets in GitHub Actions -> update runbook/ADR
     -> inspect diff and scope -> open/update PR
```

Do not claim `make it`, eval, deployment, or staging success when that target or
environment is absent. Record skipped checks and limitations in the handoff.

## Repository-wide compute policy

All compute-intensive verification MUST run in GitHub Actions. This includes Docker
Compose startup, browser/E2E tests, integration tests, database migrations, RLS proofs,
production builds, security/dependency scans, evals, and performance/load checks. Local
runs are limited to lightweight syntax, unit, lint, type, and diff checks. A local pass
must never be reported as a substitute for a missing or failed Actions result.

M0 acceptance evidence runs through the production deployment chain and its
`verify-production-oidc.yml` and `verify-production-rls.yml` checks. Required
production configuration and secrets are external prerequisites; never commit or print
credentials, tokens, passwords, private paths, or tenant content.

## Stop and ask before

- Changing curriculum weights, exam blueprints, pricing, or plan limits.
- Choosing or replacing a model provider, embedding model, or concrete model.
- Changing copyright, patient-data handling, retention, or deletion behavior.
- Adding a dependency not already present in lockfiles; state why in an ADR.
- Weakening RLS, auth, signed-URL, cache-isolation, or ungrounded-answer controls.
- Promoting upload-derived content into the Core Library.

## Never

- Show a pass-probability number before it has been validated.
- Emit a tutor sentence without a citation unless the explicitly reviewed
  `ALLOW_UNGROUNDED_DEFAULT` switch is on and the sentence is labelled.
- Accept DICOM uploads in v1 or use identifiable patient data in development.
- Trust development identity headers outside local development.
- Expose public object buckets, long-lived download URLs, secrets, or raw prompts.
- Present a placeholder, mock, unit test, or local shell as a passed staging exit
  test.

## Pull-request checklist

- [ ] Tests added or updated; coverage is not reduced
- [ ] RLS test added for each new tenant-scoped table
- [ ] Authorization and negative cases included for access-control changes
- [ ] Prompt version and eval evidence attached for any agent change
- [ ] Migration is expand-only or has a documented contract step
- [ ] Runbook and five-minute demo updated
- [ ] ADR updated for a material decision
- [ ] Feature is flagged according to milestone policy
- [ ] No private study data, patient data, provider key, or out-of-scope file is
      present in the diff
