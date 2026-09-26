# M4 five-minute demo — the daily study loop

- Covers: Today session runner (G4), weakness loop (G5), progress insights (G10),
  keyboard shortcuts (G12). ADR [0024](../decisions/0024-daily-study-loop.md), runbook
  [study](../runbooks/study.md).
- Data: the owner's own tenant, or a local stack seeded with **synthetic** sources only.
  Never demo from patient data. This script is not release evidence (ADR 0008).
- Before you start, you need:
  - a study profile with an exam date;
  - at least one ready source whose chunks have accepted curriculum mappings;
  - about 10 active SBA questions;
  - a few cards, one of them due.

## 0:00 — Today builds the session once

1. Open **Today**. The session card shows its steps in order: *Review due cards →
   Learn: \<topic\> → Timed SBA block → Viva prompt*. It also shows a progress bar
   (0 of 4) and the planned minutes.
2. Reload the page. It is the same session with the same questions, because it is
   built once per local day. Point out the plan panel beside it: the session is built
   from that plan.

## 0:45 — Review with the keyboard

1. Click **Start reviewing**. Press **Space** to reveal the answer, then press **3**
   (Good). The next card appears. Every card shows its citation chip; open one to
   land on the cited page in the reader.
2. Press **1** (Again) on a card, then point out *n/m reviewed*. Click **Mark step
   done**; the runner moves on to the next step.

## 1:45 — Learn from cited passages

1. **Start reading** shows the top topic's passages and nearby figures. Each has a
   citation that opens the source page.
2. Click **Mark step done**. These passages now count as studied in the coverage
   heatmap.

## 2:30 — Timed SBA block, confidence, weakness loop

1. **Start the timed block**. The clock is the server's.
2. Press **B**, then **3** (high confidence), then **Enter**. The feedback shows the
   key, why each option is right or wrong, and the citations.
3. Answer one item wrong on purpose, with high confidence. Press **Enter** to go to
   the next item.
4. Explain what the wrong answer did:
   - it created a *weakness* card, due within a day;
   - it queued a re-test, which tomorrow's block serves first. Show *1 re-test of
     earlier misses* by moving the clock or showing yesterday's session.

## 3:30 — Viva

1. **Start the viva**. With a viva, image-case or SEQ question in the bank, the answer
   is sent to the existing grader, and the step says *being marked* until the worker
   finishes.
2. Without such a question, the prompt is a cited self-review. After you answer, the
   source passage is revealed so you can compare.

## 4:15 — Finish and see progress

1. Click **Finish today's session**. The summary shows:
   - steps done;
   - cards reviewed;
   - SBA correct;
   - weighted coverage.

   Tomorrow's plan is rebuilt tonight.
2. Open **Progress**. Point out:
   - **Days remaining and pace**: *insufficient history* until sessions on a few days
     exist; then the projected coverage on exam day and the hours per day needed.
   - **Confidence calibration**: the high-confidence wrong answer counts as
     confidently wrong.
   - **Coverage by system and topic**: the heatmap. Switch to **Table** for the
     accessible view, and toggle the theme to show it works in dark mode.
3. Note what is absent: no pass-probability number anywhere.
