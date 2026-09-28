# 0040 — Every push to main deploys automatically

- Status: accepted (owner, 2026-09-28: "change that rule -- push to main triggers deployment
  immediately")
- Supersedes: ADR 0011 (manual deploys only)

## Context

Under ADR 0011, each production deploy waited for the owner's explicit OK. The owner found
the repeated confirmations slowed urgent pipeline fixes and chose automatic deploys.

## Decision

- **Trigger.** `deploy-production.yml` also runs on `workflow_run` when `CI` or `Build
  images` completes for a push to `main`.
- **Gate.** A `gate` job deploys only if all of these hold:
  - both workflows have a successful run for that exact commit (the second completion
    deploys);
  - the commit is still the head of `main`, so a late-finishing older commit never rolls
    production back.
- **Manual dispatch.** It stays for one exact SHA, for example a rollback.
- **Unchanged.** Secrets, the pinned host key, migrations and the smoke check work as
  before.

## Consequences

- A green push is live in minutes, without a confirmation round-trip.
- Only work that is ready to ship may be pushed to `main`.
- The red-build gate is the only barrier, so it must never be weakened.
- The production verification workflows run after every deploy run, including runs the
  gate skipped.

## Rejected

Keeping manual approval with a standing OK was rejected: it still needs a person to act.
