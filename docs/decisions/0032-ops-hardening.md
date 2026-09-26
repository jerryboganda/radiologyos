# 0032 — Ops hardening: model ledger, observability, rate limits, audit, MFA, prompt hygiene

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (subscription routes), ADR 0013 (tutor), ADR 0018 (data rights),
  ADR 0019 (embedding budget), ADR 0027 (free-first ingest), completion plan G20–G25, G35

**Context.** Before this change, model use through the owner's subscription was
invisible: there was no record per call and no warning when the usage window ran
out. The API wrote one JSON request log line and nothing else. No endpoint had a
rate limit. About five call sites wrote `audit_log`. Admin accounts had a
password only. Five call sites built user-turn prompts inline. Account deletion
left Keycloak sessions alive.

**Decision.**

1. **Model-call ledger (G20).** `packages/models/gateway.py` emits one
   `packages.models.ledger.CallRecord` for every target attempt. That covers
   success, error, usage limit, schema-invalid output, and quality-gate
   rejection (`rejected`, per the ADR 0027 fallback), plus streamed attempts. A
   stream the CLI cannot produce ran no model, so it is not recorded.
   - **Contents.** The record holds the agent key, route, backend, model,
     effort, outcome, error class, wall duration, input and output tokens, and
     cost. Tokens and cost are taken defensively from the transport's usage
     block: Claude Code's `usage`/`total_cost_usd`, or Mistral's
     prompt/completion counts. It also holds the tenant, user, and request ids
     from the trace context. It never holds prompt or output text.
   - **Storage.** Recorders are registered hooks, so the gateway signature is
     unchanged. `apps/worker/app/ops/llm_ledger.LedgerSink` queues records and
     writes them from one daemon thread per process, with its own event loop
     and a NullPool engine, into the new tenant table `llm_calls` (migration
     `20260926_0104`). The table has ENABLE + FORCE RLS; the runtime role may
     SELECT, INSERT, and DELETE, but not UPDATE. Rows are in the data-rights
     registry (erased directly), and there is a two-tenant proof in
     `evals/checks/test_ops_hardening_live.py`.
   - **Spike alert.** When one tenant sees more than
     `MODEL_USAGE_LIMIT_ALERT_PER_HOUR` (default 5) usage-limit errors in an
     hour, an amber `ops_alerts` row of the new kind `model_usage_limit` is
     raised and pushed to the admins. It re-arms only when it was acknowledged
     over an hour ago.
   - **Admin view.** `GET /v1/admin/model-usage` returns counts per day, agent,
     and backend. It feeds the Settings "Model calls" card.
2. **Observability (G21).**
   - **Request ids.** Every request gets a UUID request id: a valid
     `X-Request-ID` is kept, anything else is replaced. The id is echoed in the
     response. Middleware binds it in `packages/observability/trace` with the
     tenant and user. Published Celery tasks carry it as the
     `radbrain_request_id` header.
   - **Worker context.** Worker tasks bind task id, tenant id (the first task
     argument), and request id. A logging filter adds all three to every worker
     log line.
   - **Request logs.** API request logs add the route template, duration, and
     tenant id, and stay allowlisted.
   - **Readiness.** `/health/ready` names database, Redis, and object storage as
     `ok` or `unavailable`.
   - **Metrics.** `/metrics` serves Prometheus text: request counts and latency
     histograms (in process; the API is one process), rate-limit refusals, and
     job-step and model-call outcomes. The last two are counted in Redis hashes
     under `platform:metrics:*` so worker processes add to one total. Their
     labels are fixed vocabularies with no tenant or user ids. That makes them
     platform-scope counters, not a tenant cache, which is the reviewed
     exception to hard rule 7.
   - **Metrics access.** `/metrics` answers 404 to any request carrying a
     forwarding header or coming from a non-private address. With
     `METRICS_TOKEN` set, it also needs that bearer token.
   - **OpenTelemetry.** OpenTelemetry and prometheus-client are not in the
     lockfiles, so this is in-house, about 150 lines. Switching to the OTel SDK
     later is a dependency decision for its own ADR. The contextvars and metric
     names map one-to-one.
3. **Rate limits (G22).** Expensive endpoints use per-user and per-tenant Redis
   token buckets. The buckets are `tutor` (ask, ask/stream), `generate`
   (questions, cards), `upload` (sources, tutor images), `viva` (create,
   answer), and `export`.
   - **Mechanism.** One Lua script refills and takes from both buckets
     atomically, so a refusal from the tenant bucket costs the user nothing.
     Keys begin with the tenant id and expire. A refusal answers 429 with
     `Retry-After`.
   - **Configuration.** Defaults live in `core/config.DEFAULT_RATE_LIMITS`.
     `RATE_LIMITS` (JSON) overrides them and `RATE_LIMIT_ENABLED=false` turns
     them off.
   - **Redis outage.** An unreachable Redis fails open: logged once, then not
     retried for 30 s. The Lua script is checked against a Python mirror in unit
     tests. It has no live-Redis proof yet.
4. **Audit coverage (G23).** The request middleware writes one `api.<method>`
   `audit_log` row after every successful POST/PUT/PATCH/DELETE under `/v1`.
   - **Row contents.** The row has the actor, tenant, request id, the route
     template, the status, and the last `*_id` path parameter as the target.
     It never has a body.
   - **Named events.** A route that already wrote a named event through
     `ops.audit.audit` (for example `source.uploaded`) is not written twice.
     Named events now carry the request id too.
   - **Exempt routes.** These are listed in `ops/audit.py`: preview (in memory),
     the Stripe webhook (no principal), and read-only POSTs (`/library/search`,
     `/tenants/switch`).
   - **Failures.** A failed generic write is logged once and never fails the
     response.
   - **Coverage test.** `test_audit_coverage.py` walks the OpenAPI document so a
     new mutating route is covered unless it is explicitly exempt.
5. **MFA for admins (G24).**
   - **Realm.** `infra/keycloak/realm.json` adds the realm role `mfa_required`,
     included in `org_admin` and `superadmin`, and a TOTP policy (6 digits,
     30 s).
   - **Flow script.** `infra/ops/keycloak-mfa.sh` wraps `keycloak_mfa.py`. It is
     idempotent and runs through the admin REST API. It copies the built-in
     browser flow as `radbrain browser` and adds a conditional subflow
     "has `mfa_required` → OTP Form". An admin without an authenticator is sent
     to enrol one first. The generic "user has OTP configured" subflow gets a
     negated role condition, so admins are never asked twice. The script then
     binds the flow.
   - **Why a script.** A realm-import file with `authenticationFlows` replaces
     Keycloak's built-in flows wholesale, and the production realm already
     exists. So the flow is applied by script, not by import.
   - **Rollout.** The owner must enrol an authenticator at the next sign-in; see
     the production-deploy runbook. Applying it to production needs the owner's
     OK.
6. **Prompt hygiene (G25).**
   - **Templates.** User-turn templates move into the prompt YAMLs as
     `user_template`. The affected agents are page_parse v2, image_case v1,
     knowledge_extract v2, topic_classify v2, paper_topics v3,
     question_generate v1, question_check v1, seq_grade v1, and card_generate v1.
   - **Rendering.** `packages/prompts/templating.render` renders them. It is
     strict and single-pass: `{{name}}` only, every variable required, no
     extras, string values only, and inserted values are never expanded. The
     contract rejects a template that uses an undeclared input.
   - **No version bump.** The rendered text is byte-identical to the old
     f-strings, and a test asserts this, so no prompt version was bumped.
   - **Retired prompts.** The four M0 per-route placeholder prompts are marked
     `retired`. They are kept only as the scaffold fixture's references.
   - **CLI path.** The Claude CLI path is read only from Settings
     (`CLAUDE_CODE_BIN`) by every API route and worker.
7. **Data-rights leftovers (G35).**
   - **Session revocation.** Account erasure gains an `idp_sessions` step. It
     makes a best-effort Keycloak `POST /admin/realms/{realm}/users/{sub}/logout`
     as the new confidential `radbrain-ops` service client, whose service
     account holds only `realm-management/manage-users`. The outcome word is
     recorded on the job. When `KEYCLOAK_ADMIN_*` is unset it is
     `not_configured`, and it never blocks the erasure.
   - **Logs and backups.** Provider-log purge and backup expiry are documented
     in the data-handling runbook.

**Consequences.**

- One extra small transaction per model call (off the request path) and per
  successful mutation (on it).
- The ledger grows about one row per page or chunk during bulk ingest.
  Retention follows the tenant, and an account erasure deletes its rows.
- Rate limits can refuse a heavy but legitimate burst, for example a 100-file
  upload. Raise `RATE_LIMITS.upload` rather than disable limits.
- MFA locks out an admin who loses their authenticator. Recovery is a
  master-realm admin removing the OTP credential.

**Rejected.**

- An OpenTelemetry collector: a new dependency and service for one user.
- Per-tenant labels on metrics: they are tenant data in a shared store.
- Logging prompts for debugging: hard rule 4.
- Deleting the Keycloak user on erasure: the IdP account is the owner's to
  manage, and sessions are what keep access alive.
- Realm-import authentication flows: import replaces the built-in flows.
