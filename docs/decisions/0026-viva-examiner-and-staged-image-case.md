# 0026 — Viva examiner and staged TOACS image case: code-owned rules, worker-run turns

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0010 (model routes), ADR 0013 (grounded tutor), ADR 0015 (assessment engine), ADR 0018 (data rights)

Gap G6 needs a multi-turn viva and a staged image case, and spec section 8 fixes
the persona rules: no leading, no praise inflation, one level deeper per correct
answer, stop after two consecutive misses with a cited teaching point.
**Decision.** The model grades and drafts; plain code decides. Three new agents
on the existing `reason` route at `high` effort, with no tools, each with a
versioned prompt, a generated JSON Schema, and cases in `evals/fixtures/viva_v1.json`:
`viva_open/v1` (a cited scenario and first question), `viva_examiner/v1` (a
point-by-point check of the answer against the current question's **frozen, cited
expected points**, 0–4 ratings for reasoning and communication, an unsafe flag, a
cited teaching point, and two follow-ups: `escalate` one level deeper and `probe`
with a non-leading hint), and `image_case_stages/v1` (a five-stage rubric:
describe → findings → diagnosis → differentials → next step, each with a model
answer and weighted, cited points). In `packages/assessment/viva.py`, the verdict
is the matched fraction of expected points (≥ 0.75 good, ≥ 0.4 partial, else a
miss, and an unsafe answer is always a miss), code picks the follow-up, and the
session stops at two consecutive misses, the turn limit, or the server-held
deadline. The debrief is also computed in code, with no model call: a percent per
competency (knowledge = expected points matched; reasoning and differentials;
communication and structure), stage marks for an image case, and the cited
teaching points, weak turns first. **Citations fail closed:** an id is resolved
only if it was supplied for this session; an uncited expected point is dropped,
and a question, opening, or rubric left with nothing cited is treated as a model
error (retried, then the session stops as `examiner_error`), so uncited examiner
text is never shown. A stage answer is graded by the existing `seq_grade/v1`
against that stage's frozen points, and the stage's cited model answer is shown
only after grading. **Frozen answers stay hidden:** a turn's expected points
reach the client only once it is graded or the session ends. **Evidence is kept
as references only** (chunk and figure ids with provenance, never copied source
text) and is re-read from the owner's live sources at each step, so deleting a
source removes what a session can reach. **Exam use:** a prepared staged case is
stored as an `image_case` bank question whose `answer` carries `stages` and a
stage-tagged scheme. It passes the same deterministic checks and independent
`question_check` as any generated item, and only a pass makes it `active`. In an
exam, the item takes one structured answer (`[describe]…[next_step]`) graded
through the existing exam-grading job, with `stage_scores` in the result. A
staged case practised from a bank question records one attempt for item
statistics, and it is refused while that question sits in an open exam.
**Execution:** every model call runs in the worker (`radbrain.viva_step`, keyed
by session, turn, and `PIPELINE_VERSION`), outside any transaction. A duplicate
or late task is a no-op, and a usage-limit pause or model error re-queues it
under the exam-grading limits. The API holds no transaction across a model call.
The page polls while `work` is not `none`, and reading a session re-queues work
untouched for 10 minutes. We rejected the synchronous tutor pattern because a turn
can take minutes on Opus, and a worker step keeps turns resumable. **Weakness
loop:** `apps/api/app/assessment/weakness.py` turns missed and partial turns into
`WeakArea` records (ids, prompt, resolved citations, never the answer) and hands
them to sinks registered with `register_weakness_sink`, inside the owner's
tenant transaction. A failing sink is contained in a savepoint. **Data:**
migration `20260926_0018` is expand-only and adds `viva_sessions` and
`viva_turns`, with ENABLE and FORCE RLS, grants, a two-tenant runtime-role proof in
`evals/checks/test_viva_live.py`, and direct erasure in the data-rights registry.
Transcripts, answers, and prompts are never logged; only ids, turn numbers,
outcome kinds, and error codes are. **Trade-offs:** each viva turn costs one Opus
call and writes a follow-up that is discarded. The per-style turn defaults (6
FCPS-II TOACS, 10 FRCR 2B oral, 8 practice) and the optional time limit are
practice settings, not official exam formats. Voice viva stays out of scope.
Runbook: `docs/runbooks/assessment.md`; demo: `docs/demos/m5-viva-toacs.md`.
