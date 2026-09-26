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
