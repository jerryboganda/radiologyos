# Assessment engine runbook

Decision record: [ADR 0015](../decisions/0015-assessment-engine.md). Migration
`20260926_0007` (requires `20260926_0006`).

## Endpoints (all tenant- and owner-scoped)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v1/questions/generate` | `{topic?, source_ids?, type, exam_target, count<=5}`; 503 when the Claude CLI or usage window is unavailable, 502 on a model failure, 422 when no excerpt (or, for `image_case`, no described figure) matches |
| GET | `/v1/questions` | filters `type`, `exam_target`, `topic`, `status` (default `active`), `limit`, `offset`; never returns keys |
| POST | `/v1/questions/{id}/attempt` | SBA `{selected_option}` graded in code; SEQ/image/viva `{answer_text}` graded by `seq_grade`; 409 while the question is in an open exam |
| POST | `/v1/exams` | `{mode, exam_target?, topic?, count, time_limit_minutes}` (limit required for `exam`); active SBA items only |
| PUT | `/v1/exams/{id}/answers` | `{revision, answers}`; 409 `stale_revision`, `exam_time_expired`, or `exam_submitted` |
| POST | `/v1/exams/{id}/submit` | idempotent; returns the stored result on repeat |
| GET | `/v1/exams/{id}` | finalises an expired exam; includes `server_time` for the client timer |

## Operating notes

- Generation runs one generator call plus up to four parallel checker calls in
  the request. Expect one to several minutes at high effort; keep `count` small.
- `rejected` in the generate response lists deterministic failures by item
  index and reason code only; nothing is stored for them.
- Draft items (checker failed or errored) are visible with `status=draft` for
  review; they are never used in exams.
- Logs carry request ids and status codes only; excerpts, prompts, and answers
  are never logged.
- Live proof: `evals/checks/test_assessment_live.py` runs in the CI
  `RLS proof` job against a disposable database as `radbrain_app`.

## Troubleshooting

- 503 on generate/grade: check `claude` is on the API image PATH; a usage-window
  503 clears when the window resets.
- 502 on generate/grade: the API container must receive `CLAUDE_CODE_OAUTH_TOKEN`
  (Compose currently passes it to `worker` only). Granting it to `api` widens the
  subscription credential's exposure and needs owner approval; the alternative is
  moving generation and grading onto a worker queue.
- 409 `stale_revision` on autosave: the client must re-read the exam
  (`GET /v1/exams/{id}`) and resend with the returned `revision`.

## Depth slice (migration `20260926_0011`, requires `20260926_0010`)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v1/exams` | also accepts `types` (subset of `sba`, `seq`, `image_case`, `viva`; default `["sba"]`) |
| PUT | `/v1/exams/{id}/answers` | also accepts `text_answers` (`{question_id: text or null}`, up to 8000 chars) for written items; an option for a written item, or text for an SBA, is 422 `invalid_answer` |
| GET | `/v1/questions/review` | the owner's drafts in full (key, scheme, citations, `checker_reasons`) |
| POST | `/v1/questions/{id}/review` | `{action: approve, reject, or edit, ...fields}`; 409 `citations_stale`, `not_a_draft`, `already_retired`; 422 with comma-joined check codes |
| POST | `/v1/questions/stats/recompute` | recompute p-value and discrimination for the owner's items; retire failing ones |

- Written exam items show `status: pending` per item and `grading: pending` on
  the result until the worker finishes. Jobs live in `grading_jobs` (`status`,
  `runs`, `errors`, `error_code`); graded items fill into `exams.result`. The
  exam results screen re-reads every few seconds while anything is pending.
- Worker tasks: `radbrain.grade_exam_item(tenant, exam, question)` and
  `radbrain.recompute_item_stats(tenant, user)`. The worker needs the Claude
  runtime (`CLAUDE_CODE_OAUTH_TOKEN`); without it jobs pause as
  `model_unavailable` and fail after 48 deferrals (about a day).
- A job stuck `pending` or `running`: reading the exam (`GET /v1/exams/{id}`)
  re-queues jobs untouched for 10 minutes. A `failed` job is final for that
  grading version; the item scores zero and still shows the cited model answer.
- The generate response reports `duplicate_method`: `embedding` needs
  `VOYAGE_API_KEY`, otherwise `trigram`. Rejected near-duplicates carry
  `duplicate_of` and `similarity`; nothing is stored for them.
- Retirement needs at least 50 attempts: facility outside 0.25–0.85, or (with at
  least 20 exam responses) discrimination below 0.20. `item_stats.decision` is
  `insufficient`, `keep`, or `retire`; retired items carry
  `status_reason = stats:<code>` and an `audit_log` row `question.retired`.
- Review approval fails with `citations_stale` when a cited source was deleted
  or a cited page no longer exists; reject the draft or regenerate it.
- Live proof: `evals/checks/test_assessment_depth_live.py` (CI `RLS proof` job).

## Viva and staged image case (migration `20260926_0018`, ADR 0026)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v1/viva/sessions` | `{kind: viva or image_case, style: practice, fcps2_toacs, or frcr_2b_oral, topic?, figure_id?, question_id?, max_turns?, time_limit_minutes?}`; 404 `figure_not_found`/`question_not_found`; 422 `no_source_material`, `no_described_figure`, `question_not_staged`; 409 `question_in_open_exam` |
| GET | `/v1/viva/sessions` | the owner's sessions with `overall_percent` |
| GET | `/v1/viva/sessions/{id}` | transcript, current turn, `work`, debrief; finishes a session whose deadline passed while idle; re-queues work untouched for 10 minutes |
| POST | `/v1/viva/sessions/{id}/turns/{n}/answer` | `{answer_text}`; 409 `viva_examiner_busy`, `viva_turn_closed`, `viva_not_active`, `viva_time_expired` (the session is finished from its graded turns) |
| POST | `/v1/viva/sessions/{id}/end` | idempotent early end; in-flight examiner work is discarded |

- Statuses: `preparing` (opening question or stage rubric being written), `active`,
  `finished` (debrief stored), `failed` (nothing could be asked; `error_code` says why).
  `work` is `pending`/`running` while the worker holds a turn.
- Worker task: `radbrain.viva_step(tenant, session, turn, pipeline_version)`. Turn 0
  opens a viva or writes the staged rubric; turn n grades answer n and asks n+1 or
  finishes. Without the Claude runtime the step pauses as `model_unavailable` (every
  30 min, failed after 48 runs); uncited model output is `uncited_output` and retried
  like a model error (failed after 3). A session with graded turns that then fails
  finishes as `examiner_error`; one without becomes `failed`.
- `evidence_gone`: every text excerpt behind the session was deleted from the library.
  Start a new session.
- Staged cases become `image_case` bank questions (`answer.stages`), `active` only
  after `question_check` passes (otherwise a draft in the review queue). A new session
  on the same figure reuses the newest one instead of calling the model again. In an
  exam the item answer is one text with `[describe]`…`[next_step]` headings; the
  result item carries `stage_scores`.
- Weak turns go to sinks registered with
  `apps.api.app.assessment.weakness.register_weakness_sink`; with none registered they
  stay in the debrief (`weak_turns`, `weak_areas`).
- Live proof: `evals/checks/test_viva_live.py` (CI `RLS proof` job). Eval cases:
  `evals/fixtures/viva_v1.json` (synthetic, `review_required`).
