# 0009 — Identity, model provider, billing, and retention decisions

- Status: accepted
- Date: 2026-09-25
- Amends: ADR 0002 (model provider gate), ADR 0006 (preview boundary)
- Related: ADR 0004 (OIDC audience), ADR 0007 (shared platform), ADR 0008

Every choice below was made explicitly by the owner on 2026-09-25. This ADR
records them so the code can be changed to match a decision rather than the
other way round.

## Identity

**Self-hosted Keycloak.** The repository already ships
`infra/keycloak/realm.json` and a Keycloak service in the base Compose file, so
this follows the existing design rather than introducing a vendor. It costs
roughly 500 MB of RAM on the shared host, which the platform has room for.

**Institution SSO is removed from the project entirely.** No SAML, no
institutional federation, no per-institution identity configuration. This is a
scope reduction, not a deferral: the capability is not planned.

## Models

**Online providers only. No local models, ever.** The `local` route is removed
from the model routing vocabulary and the local-mode surface is deleted. This
retires slice W as originally written; the online provider boundary replaces
it.

The named-route architecture is unchanged and remains the only way to reach a
model: concrete providers and model names are configuration in
`packages/models/models.yaml`, never inline code. Checked-in defaults stay
`mock` with `external_egress_allowed: false` and `provider_gate.status:
blocked` until a provider key and a privacy review are supplied. Enabling real
egress still requires setting `approved_by_adr` to this ADR's identifier.

## Billing

**Stripe in test mode, plus manual payment as a first-class method.** Both are
real implementations behind one billing interface:

- Stripe: checkout, customer portal, signature-verified webhooks, idempotent
  event handling, plan caps, and graceful degradation.
- Manual: an offline or bank-transfer style method that an administrator
  records and approves, producing the same entitlement transition as a Stripe
  event.

No live payment credentials are configured. Test-mode keys are supplied through
the environment; the repository never contains one.

## Preview surface

> Superseded: ADR 0011 turned the preview off in production and ADR 0031
> removed it. The paragraph below is kept as history.

**Enabled behind authentication.** The non-release preview workspace is
reachable only to authenticated users with a privileged role. It remains
labelled non-release in the interface and in the API responses. This is a
narrowing of ADR 0006's "not on a production host" rule: the surface ships to
production, access-controlled, rather than being withheld.

## Capacity

**Design for the maximum plausible user count on the minimum resource budget.
No stress or saturation testing.** The shared host has roughly 3.3 GiB of
headroom and already serves about fifteen other applications, so the
engineering effort goes into efficiency — capped services, bounded queries,
connection pooling, in-process state where it is correct — rather than into
proving throughput by loading the box. The existing load check stays a small
ceiling assertion, not a capacity benchmark.

## Retention

**24 months, then purge.** Implemented as a scheduled, audited purge with a
dry-run mode. Purge covers the tenant's sources and everything derived from
them, which is the same purge semantics as a user-initiated delete. This is the
owner's legal and compliance position, not an engineering default.

## Consequences

- No local model means no offline capability and no data residency benefit from
  local inference. All model traffic is external, which makes the privacy review
  and the `external_egress_allowed` flag load-bearing.
- Manual payment adds an admin surface and therefore an authorisation and audit
  requirement that the Stripe path does not have.
- Deleting local mode removes an endpoint and its contract. Anything that
  referenced it is updated in the same change.
- The capacity policy means the system is not *proven* to a given concurrent
  user count. It is built to be frugal and bounded, and the runbook records that
  the ceiling is unverified.

## Rejected alternatives

- **Managed identity provider.** Rejected: per-user pricing, and user metadata
  leaves the box.
- **A local model such as a 1.5B GGUF on CPU.** Rejected: seconds per answer,
  plus about 1.5 GB of RAM on an already-loaded host.
- **Institution SSO.** Removed by owner decision rather than deferred.
- **Saturation testing to prove capacity.** Rejected: it would strain a
  production host serving other tenants, which the owner asked to avoid.
