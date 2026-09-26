# Five-minute demo: exam results review, grade disputes, claim-based SBA, knowledge cards

Status: a script for the owner's walkthrough. **It is not release evidence**
(ADR 0008). Running it needs a deployed build with migration `20260926_0102`, the
Claude runtime in the api and worker (for question generation and written-answer
grading), and at least one processed source with extracted claims and described
figures. Use synthetic material or the owner's own material only, never patient data.
Decision record: ADR 0029.

## 0:00 Knowledge cards (1 min)
1. On **Today**, find **Cards from your knowledge**. Choose **Cloze (claims)**, topic
   e.g. "pneumothorax", and press **Make cards**. The notice says how many were made
   and how many claims had nothing citable to blank.
2. Run it again: no new cards (one card per claim).
3. Choose **Image (figures)** and make a few image cards.
4. In **Review**, a cloze card shows the statement with an underlined blank. Press
   Space: the blank fills in, and the evidence quote and citation chip appear. The
   chip opens the reader on the evidence block.
5. On an image card, click the image to zoom and again to fit. Press Space to see the
   caption, findings, and figure citation. Rate with 1–4.

## 1:00 Claim-based SBA (1 min)
1. On **Questions**, type SBA, topic "pulmonary alveolar proteinosis", basis
   **Verified claims only**. Generate two.
2. Show the created items. The options include the topic's graph differentials
   (e.g. pulmonary oedema, pneumocystis pneumonia). Each option rationale cites a claim.
3. Pick a topic with no extracted claims and basis **auto**. The response falls back
   to passages. With **Verified claims only** the page explains that there are too
   few claims.

## 2:00 Timed exam with confidence (1 min)
1. On **Exams**, start a short timed paper that mixes SBA and SEQ.
2. On an SBA, press C to choose and 3 to set high confidence. The confidence
   buttons show the choice, and pressing 3 again clears it.
3. On an SEQ, click into the answer and type "123". The digits go into the answer,
   not into confidence. Click outside the box and press 1 to set low confidence.
4. Stay on one item for a while, switch tabs, and come back. Time pauses while the
   tab is hidden. Submit.

## 3:00 Results review (1 min)
1. The results show **Time per item** (total, median, mean, and the three slowest,
   linked to their items) and **Confidence calibration** (items, stated, and scored
   per level, with a one-line verdict). There is no pass probability.
2. Each item shows its time, your confidence, and **Jump to source →**. The link is
   bold on items that lost marks and opens the reader at the cited block.

## 4:00 Dispute a mark (1 min)
1. On a graded SEQ, open **Dispute a mark**, explain why the missed point was made,
   and send. The point then shows "Dispute open — awaiting review".
2. As the owner, open **Exams → Grade disputes**. The queue shows the stem, the
   marking point with its citation, the grader's justification, the answer, and the
   reason. Press **Accept** without a value to give full marks.
3. Back on the exam, the score and percentage have gone up. The point shows the new
   mark, and the dispute says "Dispute accepted". Reject another one to show that a
   rejected dispute leaves the score unchanged. Both actions are in the audit log
   with ids and numbers only.
