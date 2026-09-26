# 0011 — Personal-first delivery, manual deploys, and owner-tenant content rules

- Status: accepted
- Date: 2026-09-26
- Amends: ADR 0006 (preview), ADR 0008 (deployment chain), ADR 0009 (billing);
  narrows spec non-negotiable 1 and the upload-quarantine rule for the owner tenant

The owner decided on 2026-09-26 that radbrain is built **personal-first**: the
next goal is a genuinely usable study loop for the owner's own tenant (real
upload, parsing, cited search, tutor, planner, questions) on the production VPS,
ahead of M0 acceptance paperwork and SaaS work. **Deploys are manual:** commits
go straight to `main`, which runs CI and builds images, but production deploys
only after the owner explicitly approves, through `deploy-production.yml`
dispatched with one exact SHA that must be on `main` with green CI and image
builds. **Billing is parked:** the `/v1/billing` router is off unless
`BILLING_ENABLED=true`, and its plan catalogue values are placeholders pending
an owner pricing decision. **Owner content:** the owner's private study files
are ingested into the owner's own tenant only, never committed and never
promoted to the Core Library; patient identifiers burned into those slides are
kept as-is (no quarantine or redaction) in the owner tenant only, and this must
be revisited before any other person gets access. **Tutor fallback:** when the
owner's sources do not cover a question, the tutor performs web research scoped
to FCPS-II Radiology and FRCR preparation and answers with URL citations,
visibly labelled and separated from source-cited answers, so every sentence
still carries a citation. The exam targets are FCPS-II theory, TOACS/clinical,
IMM, and FRCR; curriculum weights are derived from past-paper frequency and
shown to the owner for approval.
