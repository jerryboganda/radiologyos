# 0022 — Derived schema evidence and branch-protected release checks

- Status: accepted
- Date: 2026-09-26
- Amends: [ADR 0008](0008-evidence-based-m0-acceptance.md) ("Migration state" and
  "Backup recoverability" rows, and "each as a required check on `main`")
- Related: ADR 0001 (tenant isolation), ADR 0011 (manual deploys, push to `main`),
  ADR 0018 (data-rights registry)

## Decision

ADR 0008 wrote the expected schema into the acceptance table as literals: alembic head
`20260925_0003`, 8 tables, 7 with RLS. Every migration since then has made that row
false, and the production RLS proof covered only the 7 M0 tables, while production now
has 38 tenant tables at `20260926_0014`. From now on the schema evidence is **derived,
never written down**. (1) *Migration state:* the live alembic head must equal the single
head of the migrations in the deployed revision. The restore drill
(`infra/ops/backup-restore-drill.sh`) takes that head from `EXPECTED_HEAD`, from a
checkout, or from the migrations built into the running api image. It fails if the
restored head or the live head differs. (2) *Tenant tables:* a tenant table is any
`public` table with a `tenant_id` column, plus `tenants`, read from `pg_catalog`. Every
such table must have ENABLE and FORCE row-level security. `evals/checks/test_rls_live.py`
asserts that, as the runtime role, each one returns zero rows without a valid tenant
context and refuses a foreign-tenant insert. The catalog set must equal the data-rights
registry, which `apps/api/tests/test_data_rights.py` keeps equal to the migrations, so a
missing or extra table fails. The drill checks the same RLS rule on the restored copy and
requires the tenant-table count to match the live database. (3) *Role separation:* the
runtime role is NOSUPERUSER, NOBYPASSRLS, NOCREATEDB and NOCREATEROLE. It is not a
member of the migrator role, owns no relation in `public` or `app`, and has no `CREATE`
on those schemas or on the database. The detailed two-tenant matrix for the M0 tables
stays in place. (4) *Enforcement:* "required check on `main`" means GitHub branch
protection on `main`. The `CI` jobs must be required status checks. Force-pushes and
branch deletion are blocked. Administrators may bypass for the owner's direct pushes
(ADR 0011), so protection limits history rewrites and non-admin merges, not the owner.
The production workflows (`Deploy production`, `Verify production RLS`, `Verify
production identity`) run after merge, so they cannot be pre-merge required checks. They
are enforced by the same-SHA evidence record, which `scripts/evidence_record.py`
generates for `docs/evidence/`. `infra/ops/verify-oidc.py` now also proves logout
(backchannel logout, then the refresh token is refused), refusal of an unauthorized
tenant switch, and role denial. For role denial it proves spoofed development headers
and forged web assertions are refused on admin routes, and that the admin routes follow
the membership role. With a synthetic student credential file (`--student-file`) it
also proves that a student gets 403. **Consequences:** a new tenant table or migration
is covered without editing the ADR or the tests. A deploy made after the newest nightly
dump fails the drill until a fresh dump is taken, which is the intended signal. Branch
protection with admin bypass does not stop a broken direct push, so the evidence record
and the post-deploy verification remain the real gate. Rejected: keeping hand-updated
counts (they went stale within a day), and requiring the production workflows as
pre-merge checks (impossible, because they run after deploy).
