# 0034 — Release scope: M7 is the vault export, billing is out, the reranker is M3

- Status: accepted (records the scope of the owner-approved completion plan, 2026-09-26)
- Date: 2026-09-26
- Amends: `docs/SPEC.md` milestone table (M6, M7), `docs/remaining-work.md` slices T, W, X, Y
- Related: ADR 0008 and ADR 0022 (evidence), ADR 0009 (removed scope), ADR 0011
  (parked billing), ADR 0028 (reranker), ADR 0031 (vault export), completion plan
  Phase 8

**Context.** The baseline specification ends with M7 "certified local mode", and its
M6 includes Stripe billing. ADR 0009 removed local-model mode (slice W), the mobile
wrapper, and institution SSO (slice Y) for good. ADR 0011 parked billing (slice T)
behind `BILLING_ENABLED=false` with placeholder plan values until the owner sets
pricing. As written, M7 could never be accepted, and M6 could be accepted only by
inventing prices. ADR 0028 added a reranker without saying which milestone owns it.
**Decision.** (1) *Release scope* is the baseline specification minus what ADR 0009
removed, minus billing. (2) *M6* is hardening and data rights: account export and
deletion, the retention purge (off until the owner enables it, ADR 0020), rate limits,
audit coverage, the model-call ledger with alerts, metrics and readiness, admin MFA
(ADR 0032), and the asserting backup/restore drill (ADR 0022). Billing is **out of
release scope** until the owner sets pricing. Its code and eval gates
(`test_m6_billing*.py`) stay as regression checks, but they are not release evidence,
and no release claim rests on billing. Bringing billing back needs the owner's pricing
decision, a new ADR, and its own evidence record. (3) *M7* is redefined as
**portability**. The durable, Obsidian-compatible Markdown vault is written inside the
account export (`vault/` in the ADR 0018 ZIP, ADR 0031). Every file carries its row id
in YAML front matter. `[[wikilinks]]` join concepts and sources, and every claim and
card cites its source and page, with evidence blocks for claims. The round trip is
read-only: `apps/worker/app/datarights/vault_links.read_vault` parses a vault back to
row ids, resolved links, and citations. Writing an edited vault back into radbrain
(import) is not in scope. (4) *The reranker is part of M3* (slice M, "reranking
config"). Its production eval is part of M3's evidence under completion-plan gap G32.
It is not a separate milestone. (5) *Acceptance is unchanged.* Each milestone M0–M7 is
accepted only with a same-SHA evidence record in `docs/evidence/mN.md` (format in
`docs/evidence/README.md`), a five-minute demo in `docs/demos/`, and no open critical
or high finding. M0 goes first. **Consequences:** M7 can now be accepted. Its
evidence is the `test_m7_portability.py` gate, the runtime-role export proof
`test_data_rights_live.py` in CI, and the M7 demo run on production for the same SHA.
The release gives up offline use, mobile packaging, institutional sign-in, and paid
plans; the spec's "local fallback" wording is superseded by ADR 0009. **Rejected:**
keeping M7 as certified local mode (it could never be met after ADR 0009); turning
billing on with placeholder prices to close M6 (pricing is an owner stop-gate, and
invented plan values would be simulated evidence); making the reranker its own
milestone (it refines M3 retrieval and has no separate user outcome).
