# 0013 — Grounded tutor: two agents, verified citations, durable threads

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (models), ADR 0011 (tutor web fallback), ADR 0012 (library)

The tutor answers in two steps with two versioned agents on the `reason` route
at `high` effort, rather than one agent that may browse. `tutor_answer/v1` has
**no tools** and answers only from the top 8 hybrid-search excerpts of the
caller's own library, labelled `S1`..`S8`, reporting `coverage`. Only when
coverage is not `full` and the request allows it (`allow_web`, default true)
does `tutor_web/v1` run with **WebSearch and WebFetch only**, and it receives
the question and earlier user questions but **never excerpt text**, so uploaded
content (untrusted, possibly hostile) cannot steer a web request or leak out
through one; least privilege also keeps a sources-only answer from silently
absorbing web content. Model citations are never trusted: code maps each label
back to a chunk id retrieved for *this* question (a model-supplied id or unknown
label is ignored), and accepts a web citation only as an https URL, without
credentials or odd ports, on an allow-listed domain (radiopaedia.org, rsna.org,
ajronline.org, rcr.ac.uk, acr.org, cpsp.edu.pk, ncbi.nlm.nih.gov). Segments with
no verified citation are dropped and counted; if none survive, the reply is an
explicit "Not found in your sources" notice with grounding `none`, never
uncited tutor text. Source segments come first and web segments are labelled
`origin: web`, giving grounding `sources`, `web`, `mixed`, or `none`. Migration
`20260926_0005` adds `tutor_threads` and `tutor_messages` (ENABLE+FORCE RLS,
two-tenant runtime-role proof in `evals/checks/test_tutor_live.py`); messages
attach to threads by `(tenant_id, thread_id)` and store the verified segments.
`POST /v1/tutor/ask` holds no database transaction during the model call, runs
the transport in a threadpool, answers synchronously, and returns 503 when the
Claude Code CLI is absent, 429 when the usage window is exhausted, and 502 on
other model failures. **Follow-ups:** SSE streaming; domain-scoped WebFetch
permissions in the transport (today the allow-list is enforced on citations,
not on what the web agent may read); a semantic grounding judge for
claim-to-citation support beyond the structural check; figure retrieval.
