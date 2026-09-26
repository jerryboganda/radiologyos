# 0025 — Tutor depth: streamed drafts, image questions, rolling memory, page focus

- Status: accepted (implementation; production smoke of CLI streaming pending)
- Date: 2026-09-26
- Related: ADR 0010 (models), ADR 0013 (grounded tutor), ADR 0018 (data rights),
  completion plan G7, G8, G15, G17

**Token streaming (G8).** Claude Code documents that `--json-schema` structured
output arrives only in the final result, never as deltas, so a streamed tutor
call runs `claude -p --output-format stream-json --verbose
--include-partial-messages` *without* `--json-schema`, with the same schema
appended to the system prompt as an output-format frame (`TEXT_JSON_FRAME` in
`packages/models/claude_stream.py`). Every text or tool-input delta goes to a
callback; `packages/tutor/draft.py` reads the partial JSON and emits small
`draft` operations (append/replace/shrink per segment) over the existing SSE
route. The final reply must be one JSON object and is validated against the
agent's Pydantic model as before; if the CLI prints no stream
(`StreamUnsupported`), the reply is not one object (`StreamOutputInvalid`), or
it fails validation, the gateway makes one ordinary schema-enforced call
instead, while model failures (usage limit, errors) are never retried. Grounding
is unchanged: drafts are unverified, never stored or logged, shown muted under
"Draft · not yet checked", and always replaced by the answer that passed the
citation check and the semantic judge (or discarded on error), so no uncited
sentence ever persists; `TUTOR_STREAM_DRAFTS=false` turns drafts off and keeps
every call schema-enforced. Only `tutor_answer` and `tutor_web` stream; the
judge, memory, and vision agents do not. **Image questions (G7).** `POST
/v1/tutor/images` accepts one PNG, JPEG, or WebP (sniffed by content; DICOM
refused; at most 20 MB and 40 MP), re-encodes it so EXIF/XMP/text metadata is
dropped, stores it privately at `tenants/<tenant>/tutor-images/<user>/<id>.<ext>`
(a CHECK pins the key to that prefix) and records it in the new FORCE-RLS table
`tutor_images` (migration `20260926_0017`); `GET /v1/tutor/images/{id}` streams it
to its owner only, so the browser never holds a storage URL. An ask with
`image_id` runs the existing `image_case/v1` vision agent once (the reading is
cached on the row), steers retrieval with the question plus the reading's
impression, differentials, topics, and findings, and gives `tutor_answer/v3`
the reading as a non-citable `<attached_image>` block; `tutor_web/v3` receives
only the structured findings, never text transcribed from the image, the
thread summary, or excerpts. The reading is shown labelled "AI reading of your
image · not a verified finding, not a citation"; every answer sentence is still
cited to the owner's sources or the labelled web fallback. Images are exported
(`tutor-images/` in the ZIP) and erased with the account; retention (ADR 0020)
does not yet cover them. Figure cards gain "Similar figures" (`GET
/v1/library/figures/{id}/similar`, nearest figure embeddings, keyword fallback)
and "Quiz me" (`figure_id` on `POST /v1/questions/generate`: that figure is F1 of
one SBA). **Rolling memory (G17).** A thread keeps its newest six messages
verbatim; when the summary plus uncovered messages exceed about 3,000 tokens,
the older ones are folded by `tutor_memory/v1` (extract route, no tools) into
`tutor_threads.memory_summary` with `memory_covered` and `memory_version`. The
summary is a non-citable `<thread_summary>` block, never sent to the web agent;
a failed fold keeps the old summary and retries next turn. **Page focus (G15).**
The Reader's "Ask about this page" opens `/tutor?source=&page=`; the ask carries
`focus`, whose page chunks (up to 4) and figures are retrieved first and named
in a `<reading>` block. Two-tenant runtime-role proof:
`evals/checks/test_tutor_depth_live.py`; eval cases: `evals/fixtures/tutor_v3.json`.
Trade-offs: a streamed answer that fails validation costs a second call; memory
adds one `extract` call per fold; the first question about an image adds one
`vision` call. Runbook: `docs/runbooks/tutor.md`.
