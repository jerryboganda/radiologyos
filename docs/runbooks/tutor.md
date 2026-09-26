# Tutor runbook — grounded answers, figures, judge, streaming

- Status: current (personal-first, ADR 0011)
- Scope: `/v1/tutor/*`, `packages/tutor/`, prompts `tutor_answer/v2`, `tutor_web/v2`,
  `grounding_judge/v1`; web `/tutor` and `POST /tutor/stream`
- Gates: `apps/api/tests/test_tutor_*.py` (local), `evals/checks/test_tutor_live.py`
  (GitHub Actions `migrations` job, runtime role); eval fixtures
  `evals/fixtures/tutor_v1.json`, `tutor_v2.json` (synthetic, review required)
- Related: [ADR 0013](../decisions/0013-grounded-tutor.md), [web UI](web-ui.md)

## How a question is answered

1. **Retrieve** (`status: retrieving`): the top 8 hybrid-search excerpts (`S1`..`S8`)
   and up to 4 described figures (`F1`..`F4`, from `search_figures`; figures with
   no AI description are skipped) from the caller's own library.
2. **Answer** (`answering`): `tutor_answer/v2` (reason route, no tools) answers only
   from those excerpts and figure descriptions and reports coverage.
3. **Web research** (`web_research`, only when coverage is not full and the request
   allows it): `tutor_web/v2` (WebSearch/WebFetch only) never sees excerpt text; it
   returns cited segments plus a summary of every page it read.
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
  then `answer` (the JSON body) and `done`; or one `error`
  (`{"status": 404|429|502|503|500, "detail": ...}`). A `: keep-alive` comment is
  sent every 15 s. Request validation still answers a plain 422.
- `GET /v1/tutor/threads`, `GET /v1/tutor/threads/{id}` (messages carry `judge`).
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
| `CLAUDE_CODE_BIN` | `claude` | Model runtime; absent → 503 / `error` event 503. |

## Cost and latency

A covered question makes two model calls (answer + judge); an uncovered one up
to three (answer, web, judge). The judge uses the `classify` route (300 s timeout).
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
- Logs carry ids, counts, and `judge_status` only — never question, excerpt,
  page-summary, or answer text (hard rule 4).
