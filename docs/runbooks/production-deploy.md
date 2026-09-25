# Production deploy runbook — shared platform VPS

- Status: current
- Scope: deploying radbrain to `185.252.233.186` on the shared platform stack
- Related: [ADR 0007](../decisions/0007-production-on-shared-platform.md),
  [ADR 0006](../decisions/0006-non-release-preview-mode.md),
  [ADR 0008](../decisions/0008-evidence-based-m0-acceptance.md)

Production deployment is **not** M0 acceptance by itself. Acceptance requires the
same-commit OIDC, RLS, backup, security, and compliance evidence described by ADR 0008.

## What runs where

| Component | Source | Notes |
|---|---|---|
| `radiologyos-web-1` | `ghcr.io/jerryboganda/radiologyos-web:<sha>` | joins `platform` + `nginx-proxy-manager_default`, alias `radbrain-web` |
| `radiologyos-api-1` | `ghcr.io/jerryboganda/radiologyos-python:<sha>` | FastAPI/uvicorn, 768m / 1.0 cpu |
| `radiologyos-worker-1` | same python image | Celery, concurrency 1, 512m / 0.5 cpu |
| `radiologyos-migrate-1` | same python image | one-shot `alembic upgrade head` as `radbrain_migrator` |
| Postgres / Redis / MinIO | `platform-postgres`, `platform-redis`, `platform-minio` | shared, never started by this project |

## Prerequisites

- Repo `jerryboganda/radiologyos`, branch `main`.
- `production` GitHub environment with secrets `VPS_SSH_KEY`,
  `VPS_KNOWN_HOSTS`, `VPS_SSH_HOST`, and the two RLS DSNs.
- On the host: `/opt/radiologyos/{app.env,secrets.env,platform.yml}` and
  `/opt/platform/projects/radiologyos.env`, all mode 600.

## Normal operation

Deployment is push-driven and needs no manual step:

```
push to main -> CI -> Build images -> Deploy production -> Verify production RLS
```

The deploy workflow fires on `workflow_run` of `Build images` and only when
that build succeeded for `main`, so it never races the image build. It pins the
exact 40-character commit SHA.

## Verification

```bash
# on the host
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml ps -a
docker compose --env-file app.env -f platform.yml run --rm -T migrate < /dev/null

# from inside the api container
docker exec radiologyos-api-1 python -c \
  "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/live'); print(r.status, r.read().decode())"
```

Expect `api`, `web` and `worker` healthy, `migrate` exited 0, and no published
ports in the `PORTS` column. The two-tenant runtime-role RLS proof runs in
`Verify production RLS`, tunnelling `127.0.0.1:15433` to the host's Postgres
loopback port.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `permission denied for database radiologyos` on `CREATE SCHEMA` | `CREATE SCHEMA` needs database-level `CREATE`, not just schema rights | `GRANT CREATE ON DATABASE radiologyos TO radbrain_migrator` (migrator only) |
| `No such container: radiologyos-api-1` and nothing deployed | `docker compose run` consumed the rest of the script on stdin | keep `-T` and `< /dev/null` on the one-shot `run` |
| Image pull `404 not found` | tag mismatch — `type=sha` publishes `sha-<short>` | build must also publish the bare full SHA; deploy pins it |
| `unbound variable` in a step | step read an env var declared only on other steps | declare workflow-level `env` |
| `Host key verification failed` | multi-line known_hosts secret with CRLF endings | write it with LF, no BOM, and assert with `ssh-keygen -lf` |
| `provision-project.sh` fails on `quay.io/minio/mc` 401 | MinIO privatised its registries after EOL | script now uses the `mc` inside `platform-minio` |

## Rollback

Redeploy the previous image tag; migrations are expand-and-contract, so an
older image tolerates a newer schema.

```bash
cd /opt/radiologyos
sed -i '/^RADBRAIN_PYTHON_IMAGE=/d;/^RADBRAIN_WEB_IMAGE=/d' app.env
printf 'RADBRAIN_PYTHON_IMAGE=%s\nRADBRAIN_WEB_IMAGE=%s\n' <python-ref> <web-ref> >> app.env
docker compose --env-file app.env -f platform.yml pull
docker compose --env-file app.env -f platform.yml up -d
```

Prefer `gh workflow run deploy-production.yml -f image_tag=<sha>`, which does
the same thing through the audited path.

Schema rollback is deliberately absent. Restoring a previous dump would discard
any tenant data written since; take a decision explicitly and prefer a
forward fix.

## Escalation

- Host pressure (swap climbing, load sustained above ~4 on 6 cores): lower the
  caps or move radbrain off this host. Do not raise the caps to fit a leak.
- Platform credential or schema problem: `/opt/platform/bin/provision-project.sh`
  is idempotent and safe to re-run for this project.
- Any suspected cross-tenant read: treat as a security incident. The runtime
  role is `NOBYPASSRLS` and owns no tables, so the RLS proof failing means the
  boundary is genuinely broken, not misconfigured.

## Known limitations

- **No identity provider.** OIDC variables are empty, so there is no federated
  sign-in. Selecting an IdP is an open human decision.
- **The public hostname is not yet routed.** `radiologyos.polytronx.com`
  resolves through Cloudflare but has no proxy host, so it returns HTTP 525
  (Cloudflare cannot complete an origin TLS handshake). The web container is
  reachable on the `radbrain-web` alias from inside the proxy network, so only
  the proxy host and its certificate remain.
- **Preview stays off in production.** `PREVIEW_ENABLED=false`, per ADR 0006.
- **Object storage is not mirrored off-host.** Platform backups cover
  databases nightly; MinIO buckets are not part of that job, and the platform
  has no off-host replication configured at all.
- `bin/backup.sh` is on-box only. A disk loss loses the nightly dumps.
