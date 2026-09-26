# 0031 — Retire the in-memory preview surface

- Status: accepted
- Date: 2026-09-26
- Amends: ADR 0006 (non-release preview mode), ADR 0009 ("Preview surface")
- Related: ADR 0011 (personal-first delivery), ADR 0018 (data rights), ADR 0022
  (derived evidence), completion plan G18/G19/G26/G27

## Decision

ADR 0006 allowed an in-memory, non-release preview of M1–M7 while durable
infrastructure did not exist, and ADR 0009 shipped it to production behind
authentication. ADR 0011 then made radbrain personal-first on durable, RLS-bound
routes, and production has run `PREVIEW_ENABLED=false` since 2026-09-26. The
preview duplicated every durable capability outside RLS and kept about 2,700
lines of code alive only for its own eval gates, so it is now **removed, not
disabled**: the `apps/api/app/preview` package, the six `/v1/preview/*` routers,
the `PREVIEW_ENABLED` setting (a leftover variable in an env file is ignored),
the web `/preview` page, `/api/preview` proxy and `lib/server/preview.ts`, the
preview-only mock-route gate in `packages/models/routing.py`, the preview load
smoke, and the M1–M7 preview runbooks. Every former preview path answers 404
whatever the credential; `infra/ops/check-preview-gated.py` (run by the identity
verification workflow) now asserts exactly that, and still asserts that parked
billing and `/v1/me` refuse anonymous callers. The M1–M7 eval gates
(`evals/checks/test_m*.py`, `test_determinism.py`) were re-pointed at the durable
services with in-memory repositories, recording sessions, and fake transports,
keeping the same behaviours wherever a durable equivalent exists; behaviours that
only the preview had (a capability matrix, a release-audit endpoint, `[[figure:]]`
markers, MRN quarantine that ADR 0011 turned off for the owner tenant, preview
labels) were dropped with the code, and each gate's docstring names the live
PostgreSQL proof that covers its rows. The preview's Markdown export (slice X)
is replaced by a durable **Obsidian-compatible vault** inside the account export
(`vault/` in the ADR 0018 ZIP): one file per concept, source, and card deck,
YAML front matter carrying each row id, `[[wikilinks]]` between concepts and to
sources, and every claim and card citing its source and page (claims also their
evidence blocks); user text is escaped so it cannot forge links, tags, block ids,
comments, or HTML, and `vault_links.read_vault` parses a vault back to ids,
links, and citations. `/v1/me` and `/v1/tenants/switch` now answer from the
caller's membership row (tenant name and kind), and a switch is refused (403)
for any tenant other than the caller's own. **Consequences:** ADR 0006's
exception no longer has a runtime surface; its sequencing rule for synthetic,
non-release work stays as history. Local header identity still exists for
development and tests only. A capability can now be demonstrated only through
the durable routes, so demos need a real (synthetic) tenant, which the
Playwright E2E workflow seeds. **Rejected:** keeping the preview disabled but
compiled (it rots and keeps a second, RLS-free data path in the image), and
deleting the eval gates with it (coverage would drop and M1–M7 would lose their
named checks).
