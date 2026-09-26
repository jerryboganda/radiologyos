# 0010 — Model routes run on Claude Opus 5.5 through the owner's subscription

- Status: accepted
- Date: 2026-09-26
- Supersedes: ADR 0002 (model provider gate); amends ADR 0009 (Models)

The owner decided on 2026-09-26 that every named model route (`reason`,
`extract`, `classify`, `vision`) runs on **Claude Opus 5.5 (`claude-opus-5-5`)**
through the owner's own **Claude Max subscription**, invoked headless on the
production VPS with Claude Code (`claude -p --model ... --effort ...
--output-format json --json-schema ...`). The subscription credential is a
long-lived token from `claude setup-token`, held only in a root-only host file
and never in git, CI, or the browser. Effort is `high` on every route except
bulk page transcription during ingest, which runs at `medium` and escalates to
`high` for figures and low-confidence pages. Embeddings use **Voyage AI**,
because Anthropic offers no embedding model; its key is also host-only.
Concrete model names, effort levels, and the transport stay in
`packages/models/models.yaml`, never inline, and the named-route boundary,
versioned prompts, output schemas, and eval fixtures remain mandatory. The
spend cap becomes a usage-window budget: bulk ingest is throttled against the
subscription's 5-hour and 7-day windows. **Limit:** Anthropic's terms allow
subscription credentials only for the subscriber's own use, so this ADR covers
the owner's personal tenant. Before any other person uses model-backed features,
routes must move to API-key authentication in a new ADR.
