# 0007 — Run production on the shared platform VPS

- Status: accepted
- Date: 2026-09-25
- Supersedes: nothing. Narrows the scope of ADR 0005 (compute policy) for this
  project only.
- Related: ADR 0006 (non-release preview mode), `/opt/platform/PLATFORM-RULES.md`

## Context

radbrain needed a deployment target. The only infrastructure available is the
existing VPS at `185.252.233.186`, which runs a shared platform stack
(`/opt/platform`: one Postgres, one MinIO, one Redis, one Soketi) plus roughly
fifteen application stacks. `AGENTS.md` states that the protected `staging`
GitHub Environment is the only environment authorised to execute M0 staging
acceptance, and the platform rules forbid any project from running its own
backing services.

Two options were available: provision dedicated backing services for radbrain,
or join the shared platform. The owner directed the shared platform, on the
explicit condition that the deployment be lightweight and must not strain the
host.

## Decision

radbrain production runs on the shared platform VPS, using the platform's
Postgres, Redis and MinIO. It starts no backing service of its own and
publishes no host port.

- Database `radiologyos` on `platform-postgres` (PostgreSQL 17.10, pgvector
  0.8.5), created by `/opt/platform/bin/provision-project.sh`, which also
  issues the per-project MinIO bucket and key, the Redis ACL user, and the
  Soketi app.
- Two database roles exist inside that database. `radbrain_migrator` owns the
  `public` and `app` schemas and is the only role that may `CREATE`; it is not
  a superuser and cannot create roles or databases. `radbrain_app` owns
  nothing, has `NOBYPASSRLS`, and holds `CONNECT` plus `SELECT`/`INSERT`/
  `UPDATE`/`DELETE` on the tenant tables. Row-level security is enforced
  against the runtime role.
- Containers join the external `platform` network and reach services by name
  (`platform-postgres:5432`, `platform-redis:6379`, `platform-minio:9000`).
  The web container also joins `nginx-proxy-manager_default` with the alias
  `radbrain-web`, which is what the proxy host forwards to.
- Every service sets `cpus` and `mem_limit`. Steady-state cap is 1.5 GiB across
  three long-running containers, and Celery runs at concurrency 1 with no
  local model.
- Backups need no new work: `platform`'s `bin/backup.sh` enumerates databases
  dynamically, so `radiologyos` is included in the nightly dumps from the
  first night onward.

## Consequences

- Three additional containers instead of roughly six. Postgres and MinIO were
  measured at 83 MiB and 261 MiB of actual use, so the shared services are
  effectively free at this size.
- CI holds exactly one credential for this host: a dedicated
  `gha-deploy-radiologyos` deploy key, added to `/root/.ssh/authorized_keys`
  following the existing convention for this box. Database, Redis and MinIO
  credentials never leave the host; compose reads `/opt/radiologyos/app.env`
  (mode 600).
- `docker/build-push-action` and the metadata action disagree about the
  `file:` input and about SHA tag formats. Both are now pinned explicitly:
  `file:` is workspace-relative, and the build publishes the bare 40-character
  commit SHA as a tag so the deploy can pin it.
- Host capacity is the main ongoing risk. The box had 3.9 GiB available and
  4.3 GiB of swap already in use before this deployment. Resource caps are
  the mitigation; if the host comes under sustained memory pressure, the
  correct response is to move radbrain off it, not to raise the caps.
- `bin/provision-project.sh` needed a fix to be usable: it referenced
  `quay.io/minio/mc`, which now returns 401 because MinIO privatised its
  registries after community end-of-life. It now uses the `mc` binary already
  present inside `platform-minio`, so provisioning needs no external image.
  The original file is preserved alongside as a timestamped `.bak-`.

## What this decision does not do

- It does not satisfy M0 staging acceptance. That gate still requires the
  protected `staging` environment, its reviewers, and human approval
  references, and it is unchanged.
- It does not enable the non-release preview surface on the public host.
  `PREVIEW_ENABLED` is `false` in `app.env` per ADR 0006; the preview surface
  is verified from inside the platform network, not exposed publicly.
- It does not select an identity provider. The OIDC variables are empty, so
  the deployment runs without federated sign-in. Choosing an IdP is a human
  decision.

## Rejected alternatives

- **Dedicated Postgres, Redis and MinIO for radbrain.** Rejected: violates
  platform rule 1 and adds roughly 1.5–2 GiB of committed memory to a host
  that is already using swap.
- **Deploying the built image on the host instead of GHCR.** Rejected: the host
  has 0 self-hosted runners, and building there would work against the
  owner's instruction not to strain it.
- **A long-lived GHCR read token on the host.** Rejected: the deploy job mints
  a short-lived `GITHUB_TOKEN`, uses it for the pull only, then shreds it and
  logs the registry out through an `EXIT` trap.
