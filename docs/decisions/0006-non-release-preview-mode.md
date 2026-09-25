# ADR 0006: Non-release preview implementation mode

Status: **Accepted for local development; staging and release gates remain unchanged**
Date: 2026-09-25
Decision owners: product and engineering
Scope: implementation sequencing for M1–M7 preview work

## Context

The protected M0 staging Environment is not provisioned. The product specification
requires milestone staging evidence before a later milestone can be claimed complete.
Waiting for external infrastructure would prevent useful local development, but
silently treating CI, mocks, or local tests as release acceptance would make the
milestone status false and could expose unsafe assumptions.

## Decision

This ADR is the explicit exception to the implementation-start sentence in
[`AGENTS.md`](../../AGENTS.md), [`CLAUDE.md`](../../CLAUDE.md), and
[`remaining-work.md`](../remaining-work.md). It permits later-slice implementation in
preview mode; it does not supersede any staging exit test, human approval, or release
claim gate.

Allow implementation of later slices in an explicit non-release preview mode when the
following conditions hold:

1. Work uses synthetic fixtures, reserved UUIDs, mock/local model routes, and local
   in-memory adapters only.
2. Tenant IDs, object keys, cache keys, and job ownership remain server-derived and
   isolated; preview convenience never bypasses RLS or authorization. Any in-memory
   preview store is local-only and is not RLS evidence.
3. Every route or screen is labelled preview/non-release in API metadata or UI where
   applicable; no staging, production, clinical, billing, or provider claim is made.
4. Migrations remain expand-only and every new tenant table receives RLS and a
   non-privileged negative test before it can be considered implementation-complete.
5. The M0 acceptance gate remains required for release. A green local check, mock route,
   placeholder, or preview UI cannot close M0 or unlock a release claim. ADR 0008 defines
   that gate as automated evidence rather than human sign-off.
6. Provider, pricing, curriculum, retention, legal, and clinical decisions remain
   deferred unless a separate explicit human decision and ADR exists.

Preview mode is a development sequencing aid, not a waiver of privacy, security,
provenance, or evidence requirements. It must be removed or disabled before a release
candidate is created.

### Amendment by ADR 0009

The preview surface is enabled on the production host behind authentication, which
narrows the original "local and test environments only" rule. The conditions above
still hold in full: synthetic fixtures, server-derived tenant context, RLS, a
non-privileged negative test per tenant table, and preview labelling everywhere.
The amendment is only about *where* the surface runs, not about what it may claim.
Access is a verified OIDC token whose membership is resolved from the database;
header-based identity remains local-only, and the application refuses to start with
preview enabled outside local development unless an identity provider is configured.

## Consequences

- M1–M7 code can be built and exercised locally while staging infrastructure is absent.
- Acceptance status must distinguish `preview implemented` from `staging accepted` and
  `release approved`.
- Mock outputs cannot be used as medical, billing, or model-quality evidence.
- Final release remains blocked until the protected M0–M7 staging evidence and approvals
  required by [`remaining-work.md`](../remaining-work.md) exist.

## Rejected alternatives

- **Delete the milestone gate:** permits untested later capabilities to be presented as
  accepted and weakens tenant/security evidence.
- **Use CI as staging:** CI cannot prove real OIDC membership, deployment configuration,
  human approval, or protected runtime behavior.
- **Silently choose providers or product policy:** would bypass the existing decision
  owners and create privacy, legal, clinical, or commercial commitments.

## Verification

- Unit and contract tests run locally for deterministic preview behavior.
- Heavy integration, browser, database, security, and performance checks run in GitHub
  Actions when the candidate is published.
- Release verification requires the automated evidence chain defined by ADR 0008;
  preview mode alone never satisfies it.
