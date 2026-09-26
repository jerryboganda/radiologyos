# 0024 — Daily study loop: Today sessions, weakness loop, progress insights

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0014 (planner and FSRS), ADR 0015 (assessment engine),
  ADR 0018 (data rights), spec section 7, completion plan G4, G5, G10, G12

**Decision.** Migration `20260926_0016` adds `study_sessions`, `study_session_steps` and
`weakness_events`, each tenant-scoped with ENABLE + FORCE RLS, runtime grants, a
two-tenant runtime-role proof (`evals/checks/test_study_sessions_live.py`) and a
data-rights registry entry. It also adds the nullable `attempts.confidence` (1 low,
2 medium, 3 high) and widens the `cards.origin` check to allow `weakness`: the check is
replaced in one statement by a strict superset, so every existing row and writer
stays valid (the only `DROP` in the upgrade is that constraint swap).
`GET /v1/study/sessions/today` builds the day's session **once per user and local
day** (unique row; a concurrent build keeps the first) from the cached day plan, in
the spec's order: due cards (plus today's new cards) → a learn step of cited chunks
and nearby described figures for the plan's top topic (curriculum mappings or cards
anywhere in that node's subtree, skipping passages already read in a finished learn
step) → a timed SBA block sized by the plan's test block (max 20, 1.5 min per item;
open weakness re-tests first, capped at 40 %, then 60 % of the rest from today's
topics, then weak topics, then anything, never-attempted and least-recent first,
seeded per user and day) → one viva prompt. A step with nothing citable is left out.
Steps are started, answered and completed through
`POST /v1/study/sessions/{id}/steps/{n}/start|answer|complete` (idempotent: the
first answer stands). The SBA clock starts at `start` and the server refuses
answers 30 s after the deadline. A viva prompt uses an active viva, image-case or SEQ
question when one exists. It is graded by the **existing async `seq_grade` path**:
the answer becomes a submitted one-item practice exam (`config.kind =
session_viva`) whose grading job the worker runs. Otherwise the prompt is a
self-review question built from the learn step's first chunk: the answer is stored
on the step, and the cited passage is revealed afterwards for comparison. Session
rows hold ids, statuses and the user's own answers only. Passages, cards, figures
and questions are read live, with their citations, under RLS. Keys and explanations
appear only for answered items. `POST /v1/study/sessions/{id}/complete` skips
unfinished steps and freezes a summary: reviews, SBA results, minutes (wall time,
capped per step) and weighted coverage. It then deletes tomorrow's cached plan, so
the existing nightly replan rebuilds it from fresh mastery.
**Weakness loop:** a wrong SBA answer, from a practice attempt, a session or a
submitted exam, creates a `weakness` card for that question, or resets the one made
earlier. The card cites the chunk the question cites, starts in state `learning`
and is due after one day, inside the spec's two-day window. The answer also opens a
`weakness_events` re-test due within two days; the next session's SBA block picks
it up, and any later answer to that question closes it. A card rated Again already
relearns in 10 minutes under FSRS, so a lapse only queues a re-test of an active SBA
question on the card's chunk. Events are unique per (kind, attempt or review id), so
replaying an attempt changes nothing. A question whose chunk has no curriculum
mapping gets a card labelled `UNMAPPED`: it can be reviewed but is outside
mastery.
**Insights:** `GET /v1/study/insights` returns three things, none of them a pass
probability:
- a system × topic coverage heatmap for a curriculum of any depth: children of each
  system are cells, deeper codes roll up, and a flat system has one cell. A cell's
  value is the share of mapped passages the user has studied;
- a days-remaining projection. Pace is measured from completed sessions' frozen
  weighted coverage over 28 days, needs at least 3 days of span, and otherwise says
  so. It reports projected coverage on exam day and the minutes per day needed to
  reach 90 % weighted coverage 30 days before the exam;
- a calibration bias. Low, medium and high confidence are read as 0.40, 0.65 and
  0.90; the bias is shown after 10 rated answers, along with confidently-wrong counts.
  It is never folded into mastery.

**Keyboard shortcuts (G12)** live in `apps/web/src/lib/shortcuts.ts`:
- Card review: Space reveals, 1–4 rate.
- SBA in the session: A–E choose, 1–3 set confidence, Enter submits or moves on.
- Exams: A–E choose.

Shortcuts are ignored while typing (text inputs, textareas, selects, contenteditable)
or with a modifier held. Controls carry `aria-keyshortcuts` and a visible `<kbd>`
hint.

**Why.** Reusing the plan, FSRS scheduler, exam grader and attempt table keeps one
source of truth for mastery. Freezing coverage at completion makes pace an
observation rather than an assumption. Storing ids rather than text keeps session
rows free of source content, so deleting a source cleans them up. Deferred to later
packages:
- cloze and image cards (G9);
- results review and disputes (G11);
- confidence capture inside timed exams;
- per-topic mastery beyond coverage and accuracy.
