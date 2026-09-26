# M0 foundation — five-minute demo

- Status: a script for a live demo; **not release evidence by itself** (ADR 0008).
  The evidence is the same-SHA record in [`docs/evidence/m0.md`](../evidence/m0.md).
  This demo only walks through it.
- Needs:
  - the deployed production revision (`https://radiologyos.polytronx.com`) and its
    40-character SHA;
  - a signed-in browser for a synthetic user or the owner's own account;
  - the `gh` CLI signed in with read access to the repository;
  - an operator shell on the host for the health step (optional; the workflow logs
    show the same checks).
- Model credentials: **none**. Nothing in M0 calls a model.
- Do not dispatch any workflow during the demo. A deploy needs the owner's explicit
  OK (ADR 0011). The demo shows runs that already exist.
- Related: [M0 runbook](../runbooks/m0-foundation.md),
  [production deploy](../runbooks/production-deploy.md), ADR 0001, ADR 0008, ADR 0022.

## 0:00 — Sign in through OIDC

1. Open the site signed out. The home page shows the sign-in screen and no data.
2. Click **Sign in**. The browser goes to the Keycloak `radbrain` realm. Sign in.
   If the admin MFA rollout has been applied (ADR 0032) and the account is an
   admin, a 6-digit authenticator code is asked for.
3. After the callback, point at the address bar: no code, token or secret is in
   the URL.
4. Open **Settings**. It shows the signed-in user's name, email and role. The role
   comes from the membership row, not from the token (ADR 0031).
5. Open the browser's storage panel. `localStorage` holds no token; the session is
   an HTTP-only cookie (hard rule 6).

## 1:00 — Tenant isolation proof

1. Run `gh run list --workflow verify-production-rls.yml --limit 3` and open the
   run for the deployed SHA with `gh run view <run id>`.
2. In the log, point out:
   - the proof connects as the runtime role, which is `NOBYPASSRLS` and owns
     nothing;
   - the table list is read from `pg_catalog`, so every `tenant_id` table is
     covered (ADR 0022);
   - for each table: ENABLE + FORCE RLS, zero rows without a tenant context, and
     a refused foreign-tenant insert;
   - the two-tenant matrix for the M0 tables: A cannot read or write B's rows,
     and B cannot read or write A's.
3. The log holds no DSN, password or tenant content; only test names and counts.

## 2:00 — Identity checks and health

1. Open the latest `Verify production identity` run
   (`gh run list --workflow verify-production-oidc.yml --limit 3`). The steps of
   `infra/ops/verify-oidc.py` show:
   - sign-in and token checks pass;
   - a switch to a random tenant gets 403;
   - spoofed development headers and forged web assertions get 401 on admin
     routes;
   - after a backchannel logout, the refresh token is refused;
   - former `/v1/preview/*` paths answer 404 (`check-preview-gated.py`).
2. On the host, run the readiness call from the production runbook
   (`docker exec radiologyos-api-1 python -c "…/health/ready…"`). Expected:
   `{"checks": {"database": "ok", "redis": "ok", "object_storage": "ok"}}`.
3. `docker compose --env-file app.env -f platform.yml ps -a` shows `api`, `web` and
   `worker` healthy, `migrate` exited 0, and nothing in the `PORTS` column.

## 3:00 — The deploy chain

1. `gh run list --branch main --limit 6`: each push ran `CI`, `Build images` and
   `E2E`. None of them deployed.
2. `gh run list --workflow deploy-production.yml --limit 3`: every deploy is a
   `workflow_dispatch` for one exact SHA. Explain the guard: the job refuses unless
   the SHA is on `main` and `CI` and `Build images` both succeeded for it.
3. Show that the two verify workflows ran after the deploy and checked out the
   deployed revision, not `main`'s tip.
4. Mention branch protection on `main`: `CI` jobs are required checks, and
   force-pushes and branch deletion are blocked (ADR 0022).

## 4:00 — The evidence record

1. Run `python scripts/evidence_record.py <deployed sha>`. It prints one row per
   workflow (`CI`, `Build images`, `Deploy production`, `Verify production RLS`,
   `Verify production identity`) with run id, status and conclusion, then
   *Same-SHA evidence: all green* or *NOT all green*. It exits non-zero unless all
   five passed.
2. Open [`docs/evidence/m0.md`](../evidence/m0.md). It holds that table, the restore
   drill summary pasted unedited (`backup-restore-drill.sh`: head, RLS tables,
   extensions, RPO and RTO), and the compliance result.

## 4:40 — Verdict

- M0 is accepted only when every row in the record is green for the same SHA and
  the drill passed on that head. Otherwise, name the missing item.
- Open limitations to state aloud:
  - no person signs off on security, privacy or legal questions (ADR 0008);
  - admins can bypass branch protection for direct pushes, so the post-deploy
    verification is the real gate (ADR 0022).
