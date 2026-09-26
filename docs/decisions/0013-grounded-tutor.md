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
claim-to-citation support beyond the structural check; figure retrieval (all
but the WebFetch scoping are delivered in v2 below).

## v2 — figures, semantic grounding judge, SSE progress (2026-09-26)

The structural check proves a citation names retrieved evidence, not that the
evidence says what the segment claims, so every answer now also passes a
**semantic grounding judge**: `grounding_judge/v1` (classify route, `high`
effort, no tools, output `JudgeVerdicts`) sees each segment beside the text of
exactly the evidence it cites and returns `supported | partial | unsupported`
with a short reason. Unsupported segments are dropped and counted; partial ones
are kept with a visible "Partially supported" label; if the judge fails (any
model error, including the usage limit), returns no verdict for a segment, or is
switched off, segments are kept but labelled "Not verified" rather than silently
presented as checked. Only the explicit deployment setting
`TUTOR_GROUNDING_JUDGE` (default true) can skip it; a request cannot. Judge
stats (`JudgeStats`) are returned and persisted with the message: migration
0005 constrains `citations` to a jsonb array, so the segments are followed by
one trailing `{"kind": "judge_stats", "judge", "dropped_segments"}` element, and
the reader accepts rows without it, so no migration is needed. Web segments are
judged against the page summaries that `tutor_web/v2` (output
`WebAnswerWithPages`) now returns for every page it read; without a summary a
web segment stays labelled "From the web" only. **Figures:** up to four
described figures from `search_figures` are passed to `tutor_answer/v2` as
labelled AI descriptions `F1`..`F4`; a figure label resolves in code to
`figure_id` + page (model-supplied ids are ignored, unknown labels dropped) and
renders as a thumbnail through the authenticated `/media/figures/{id}` proxy.
**Streaming:** `POST /v1/tutor/ask/stream` returns Server-Sent Events —
`status` (`retrieving`, `answering`, `web_research`, `judging`), then `answer`
(the JSON route's body) and `done`, or one `error` with the JSON route's status
(404/429/502/503) — with a keep-alive comment every 15 s. Only progress streams:
the Claude Code transport returns one validated JSON, so tokens are not
streamed. The JSON route stays, and the web page falls back to it when the
stream cannot be opened or ends without an answer. v1 prompts are retired but
kept for provenance of stored `agent_version` values; eval cases live in
`evals/fixtures/tutor_v2.json`. Trade-off: one extra `classify` call per answer.
Still open: domain-scoped WebFetch permissions in the transport; judge accuracy
measured against a reviewed eval set. Runbook: `docs/runbooks/tutor.md`.
