# Tutor runbook — grounded answers, figures, judge, streaming, images, memory

- Status: current (personal-first, ADR 0011)
- Scope: `/v1/tutor/*`, `packages/tutor/`, `packages/models/claude_stream.py`, prompts
  `tutor_answer/v3`, `tutor_web/v3`, `tutor_memory/v1`, `grounding_judge/v1`,
  `image_case/v1`; web `/tutor`, `POST /tutor/stream`, `POST /tutor/image`,
  `/media/tutor-images/{id}`, the Reader's "Ask about this page", and figure-card
  "Similar figures" / "Quiz me"
- Gates: `apps/api/tests/test_tutor_*.py`, `test_model_streaming.py`,
  `test_figure_actions.py` (local); `evals/checks/test_tutor_live.py` and
  `test_tutor_depth_live.py` (GitHub Actions `migrations` job, runtime role); eval
  fixtures `evals/fixtures/tutor_v1.json`, `tutor_v2.json`, `tutor_v3.json`
  (synthetic, review required)
- Related: [ADR 0013](../decisions/0013-grounded-tutor.md),
  [ADR 0025](../decisions/0025-tutor-depth.md), [web UI](web-ui.md)

## How a question is answered

0. **Attached image** (`reading_image`, only with `image_id` and no cached reading):
   `image_case/v1` (vision route, Read tool) reads the owner's image once; the
   reading is cached on the `tutor_images` row.
1. **Retrieve** (`status: retrieving`): the top 8 hybrid-search excerpts (`S1`..`S8`)
   and up to 4 described figures (`F1`..`F4`, from `search_figures`; figures with
   no AI description are skipped) from the caller's own library. The query is the
   question plus the image reading's impression, differentials, topics, and
   findings. With `focus` (Reader page), up to 4 chunks and the figures of that
   page come first.
1b. **Memory** (`remembering`, only when needed): when the rolling summary plus the
   uncovered messages exceed ~3,000 tokens, all but the newest 6 messages are
   folded into `tutor_threads.memory_summary` by `tutor_memory/v1`. A failed fold
   keeps the old summary and retries next turn.
2. **Answer** (`answering`): `tutor_answer/v3` (reason route, no tools) answers only
   from those excerpts and figure descriptions and reports coverage. The thread
   summary, image reading, and Reader page ride along as non-citable context blocks.
3. **Web research** (`web_research`, only when coverage is not full and the request
   allows it): `tutor_web/v3` (WebSearch/WebFetch only) never sees excerpt text, the
   thread summary, or text transcribed from an image; it may receive the image's
   structured findings. It returns cited segments plus a summary of every page it
   read.
4. **Citation check** (code): labels map back to chunk/figure ids retrieved for this
   question; web URLs must be https on the allow-list. Uncited segments are dropped.
5. **Grounding judge** (`judging`): `grounding_judge/v1` (classify route, high
   effort, no tools) reads each segment beside the text of exactly what it cites
   and returns `supported`, `partial`, or `unsupported`.
   - `unsupported` → dropped (counted in `dropped_segments` and `judge.unsupported`);
   - `partial` → kept, labelled **Partially supported** (reason as a tooltip);
   - judge failure, usage limit, missing verdict, or judge switched off → kept,
     labelled **Not verified**;
   - web segments without a page summary are not judged and stay labelled
     **From the web**.
6. The exchange is stored; the assistant message's `citations` jsonb array holds
   the segments followed by one `{"kind": "judge_stats", "judge": {...},
   "dropped_segments": n}` element (older rows have no such element and still read).

## Routes

- `POST /v1/tutor/ask` — JSON answer (`judge` stats, `figures_considered`).
- `POST /v1/tutor/ask/stream` — Server-Sent Events: `status` (`{"stage": ...}`),
  `draft` operations while answer and web steps are written
  (`{"phase": "sources"|"web", "segment": n, "append"|"text": ...}` or
  `{"phase", "count": n}`), then `answer` (the JSON body, which replaces every
  draft) and `done`; or one `error` (`{"status": 404|429|502|503|500, "detail": ...}`).
  A `: keep-alive` comment is sent every 15 s. Request validation still answers a
  plain 422.
- Ask body extras: `image_id` (from `POST /v1/tutor/images`; 404 unless the caller
  uploaded it) and `focus: {"source_id", "page_no"}` (404 unless the caller's source).
- `POST /v1/tutor/images` (multipart `file`) → 201 `{image_id, content_type,
  byte_size, width, height}`; 415 for anything but PNG/JPEG/WebP (DICOM named
  explicitly), 413 over 20 MB or 40 MP. `GET /v1/tutor/images/{id}` → the bytes, owner
  only, `Cache-Control: private, max-age=300`.
- `GET /v1/library/figures/{id}/similar?limit=8` → nearest figures of the caller's
  own library (figure embeddings; keyword fallback for undescribed/unembedded ones).
- `POST /v1/questions/generate` with `figure_id` → that figure is F1 of the item(s);
  with no topic its caption/description steers retrieval (404 not yours, 422 not
  described yet).
- `GET /v1/tutor/threads`, `GET /v1/tutor/threads/{id}` (messages carry `judge`;
  user messages carry `image_id` and the cached `image_reading`).
- Web: `POST /tutor/stream` (same-origin JSON, signed-in only) proxies the SSE via
  `apiFetch`; the page falls back to the `?/ask` form action (JSON route) when the
  stream cannot be opened or ends without an answer. An `error` event is shown,
  not retried.
- Figure citations render as thumbnails from `/media/figures/{figure_id}` and link
  to the cited page in the reader.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `TUTOR_GROUNDING_JUDGE` | `true` | Run the semantic judge. `false` is an explicit deployment decision; answers are then labelled "Not verified" and `judge.status` is `skipped`. |
| `TUTOR_STREAM_DRAFTS` | `false` | Off until the owner accepts showing uncited drafts (CLAUDE.md). `true` streams labelled draft text over SSE. `false` = progress only; every call is schema-enforced JSON. |
| `CLAUDE_CODE_BIN` | `claude` | Model runtime; absent → 503 / `error` event 503. |

## Cost and latency

A covered question makes two model calls (answer + judge); an uncovered one up
to three (answer, web, judge). Add one `vision` call the first time an image is
asked about, and one `extract` call whenever memory folds. A streamed answer that
is not one valid JSON object costs one extra, schema-enforced call. The judge uses the `classify` route (300 s timeout).
The nginx proxy's 300 s read timeout is kept open by the keep-alive comments;
the web proxy aborts the upstream stream after 15 minutes or when the browser
disconnects (the model call already running finishes in its thread, but that
answer is neither delivered nor stored).

## Troubleshooting

- **Every answer says "Not verified".** Check `judge.status` in the response or
  the stored message: `failed` means the judge call failed (usage window, invalid
  output) — answers are still citation-checked; `skipped` means
  `TUTOR_GROUNDING_JUDGE=false`.
- **Answers lost many sentences.** `judge.unsupported` counts sentences the
  judge found unsupported by their citations; this is intended behavior.
- **No figures cited.** Figures need an AI description (library `extract_figures`
  step) and must match the question's terms.
- **Progress never appears but answers arrive.** The stream failed and the page
  used the JSON fallback; check proxies for buffering (`X-Accel-Buffering: no` is
  sent) and the web container logs.
- **Progress appears but no draft text.** The CLI did not stream deltas (check
  `claude --version`; `--include-partial-messages` is required) or
  `TUTOR_STREAM_DRAFTS=false`. Answers are unaffected: the gateway falls back to a
  schema-enforced call.
- **Image upload refused.** 415 = not PNG/JPEG/WebP by content (screenshots of
  DICOM viewers are fine; `.dcm` files are not); 413 = over 20 MB or 40 MP. The web
  server's `BODY_SIZE_LIMIT` (310 MB) is not the limit.
- **Follow-ups lose context in long threads.** Check `tutor_threads.memory_covered`
  and `memory_version`; `tutor_memory_failed` warnings mean folds are failing
  (usage window) and only the newest turns are sent.
- Logs carry ids, counts, and `judge_status` only — never question, excerpt,
  page-summary, draft, image, or answer text (hard rule 4).
