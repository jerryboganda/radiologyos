# Five-minute demo: M5 viva examiner and staged TOACS image case

Status: a script for the owner's walkthrough. **It is not release evidence**
(ADR 0008). Running it needs a deployed build, the Claude runtime
(`CLAUDE_CODE_OAUTH_TOKEN`) in the api and worker, and at least one processed
source with described figures. Use synthetic or the owner's own material only,
never patient data.

## 0:00 Set-up (30 s)
1. Sign in and open **Viva** in the navigation (the "More" menu on mobile).
2. Point out the two session kinds and the formats: practice, FCPS-II TOACS/viva,
   and FRCR 2B oral.

## 0:30 Viva on a topic (2 min)
1. Kind **Viva**, format **FCPS-II TOACS / viva**, topic e.g. "pulmonary alveolar
   proteinosis", time limit 10 minutes. Press **Start**.
2. The page says the examiner is reading your sources, then shows the cited
   scenario and Q1 (a level-1 recognition question). Show that the citation chips
   open the source page.
3. Answer well, and send with Ctrl+Enter. While it marks, the page shows
   "marking your answer". Q2 then arrives one level deeper ("Deeper · level 2").
   Open **Marking for Q1**: each expected point shows matched/partial/missed with
   its citation, then the feedback and the cited teaching point.
4. Answer Q2 wrongly. The next question is a **Probe** with a non-leading hint
   (a partly right answer also gets a probe, but does not count as a miss).
   Answer the probe wrongly too. The session stops with "Stopped after two consecutive
   misses" and shows the debrief: overall %, one bar per competency (knowledge,
   reasoning and differentials, communication and structure), and the teaching
   points with the weak ones first.

## 2:30 Staged image case (1 min 45 s)
1. From **Questions**, choose **Viva on this image** under an image question and
   switch the session to **Staged image case**, or start a staged case from a topic.
2. The figure opens in the zoomable viewer (+/−, 0 fit, 1 actual pixels,
   drag to pan). The station text never names the diagnosis.
3. Answer **Describe**. Once it is marked, its score, the per-point marks and the
   cited model answer appear, and **Key findings** opens. Continue to **Next step**.
4. The debrief shows the score for each stage. The case is now a bank question:
   **Questions** offers "Practise as a staged station", and an exam that includes
   image cases shows it with five stage boxes and per-stage marks in the results.

## 4:15 Safety and privacy (45 s)
- Expected answers stay hidden until a question is marked. Nothing uncited is
  shown: an uncited examiner output is retried, never displayed.
- Answering after the deadline is refused, and the session is marked from the
  turns already graded.
- Switch light and dark themes. The image stays on its dark stage.
- Logs hold ids and outcome codes only (no answers, transcripts or prompts).
