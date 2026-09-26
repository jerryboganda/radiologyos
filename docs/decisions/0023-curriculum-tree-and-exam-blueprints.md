# 0023 — Curriculum topic tree, node-level mapping, and exam blueprints

- Status: accepted (the pack and blueprint *content* stays a draft until the owner approves it in the app)
- Date: 2026-09-26
- Related: ADR 0011 (personal-first), ADR 0014 (planner), ADR 0015 (assessment), ADR 0016 (knowledge and weights), ADR 0021 (quota-aware effort)

**Decision.** The 16-system placeholder is replaced by a hierarchical radiology
pack, `packages/curriculum/radiology/` (manifest `pack.json` plus one file per
system; schema version 2). It holds 17 systems (the 16 existing codes unchanged,
plus `ANATOMY`), 115 topics, and 366 subtopics. Each node carries exam tags:
`fcps2_theory`, `fcps2_toacs`, `imm`, `frcr_2a`, `frcr_2b`. A child's tags are a
subset of its parent's. Codes are hierarchical (`CHEST` → `CHEST.PULM_VASC` →
`CHEST.PULM_VASC.PE`), so system codes and every existing mapping, card, and
system-level weight keep working. The pack status stays
`draft_pending_owner_approval` and carries no weights. The owner approves or
rejects it at `/knowledge/curriculum` (`POST /v1/knowledge/curriculum/decision`,
`org_admin`/`superadmin` only, audited). The decision is an append-only row in
`curriculum_reviews`, bound to the pack's SHA-256 content hash, so any later
edit to the tree shows as pending again.

**Mapping below system level.** Migration `20260926_0015` (expand-only) adds
`curriculum_mappings.curriculum_node_id`, the most specific node (system, topic,
or subtopic). `curriculum_code` stays the system (NULL node = system level).
`packages.knowledge.curriculum.node_mapping` validates a node id at any depth
and keeps the rule that confidence below 0.7 goes to review. The worker helper
`graph.store_node_mapping` stores the mapping. Re-coding in the review queue
accepts any node id. `packages/curriculum/candidates.py` provides
`topic_candidates(exam_targets, max_level)`, `candidate_listing()`
(`ID | System > Topic > Subtopic` lines for a prompt), and `validate_node_id`.

**Output contract for the merged classify prompt.** The owner of
`knowledge_extract`/`topic_classify` is merging those two prompts. For each
chunk, the merged prompt must emit `{"curriculum_node_id": str, "confidence":
float}`, where the id is one listed by `candidate_listing` and confidence is in
0..1. Storage goes through `node_mapping` and then `store_node_mapping`, which
drop unknown ids and send confidence below 0.7 to review. WP-B did not change any
`topic_classify` or `knowledge_extract` prompt.

**Weights by topic.** `paper_topics/v3` (effort `low`, as in v2 under ADR 0021)
names one `curriculum_node_id` per question. `page_counts` keys the topic by
that node id when it lies below system level, and by the free-text topic
otherwise. Topic-level weights therefore line up with the tree (their titles are
resolved in `GET /v1/knowledge/topic-weights`). Weights are still derived only
from past papers and approved separately (ADR 0016). The agent version changed,
so past-paper pages are re-read once. Production has no such rows yet.

**Exam blueprints.** The packaged defaults are in
`packages/assessment/blueprints.json` (10 blueprints). Each lists item counts per
type, duration, mix mode (`fixed` groups, `even` over systems tagged for the
exam, or `weights` from the owner's approved past-paper weights), negative
marking, a pass mark where one is public, `sources`, and an `unverified` list.
The new tenant table `exam_blueprints` (tenant_id, ENABLE+FORCE RLS, two-tenant
proof in `evals/checks/test_curriculum_blueprints_live.py`, data-rights registry)
stores the owner's overrides of the editable fields. Approval is bound to the
hash of the effective blueprint, and any override clears it.
`POST /v1/exams` accepts `blueprint_id` and optional `blueprint_items`, which
scales the paper down while keeping its mix and pro-rata time. The paper is
assembled per mix: largest-remainder allocation per group, preferring questions
tagged for the blueprint's exam, with any gap filled from other systems and
reported as `mix_report.shortfall`. With negative marking, a wrong SBA deducts
`penalty × mark` from the exam totals only. Item scores and `attempts` stay at
or above zero, so mastery is unaffected. Existing exam creation is unchanged.

**Research (2026-09-26); unconfirmed facts are marked `unverified`.**
- CPSP FCPS-II Diagnostic Radiology prospectus (2012). Theory is two 3-hour
  papers: Paper I has 10 SAQs and Paper II has 100 single-best MCQs. The clinical
  part is film reporting plus viva. It also gives the system-wise core
  curriculum. <https://elogbook.cpsp.edu.pk/eportal/eportal/docs/trainee/prospectus/fcps2/DiagnRad%20FCPS-II%202012.pdf>
- Radiopaedia (current format). FCPS-II theory is two BCQ papers; TOACS is a
  computer-based image assessment with 30 stations; the viva is six system vivas
  on three tables. IMM is two BCQ papers plus TOACS, covering physics, anatomy,
  and basic pathology. <https://radiopaedia.org/articles/fellow-of-college-of-physicians-and-surgeons-pakistan-diagnostic-radiology>
- CPSP IMM guideline. Computer-based Diagnostic Radiology has Paper I and Paper
  II, each 100 MCQs in 2 hours; TOACS follows 2–3 weeks later.
  <https://www.cpsp.edu.pk/files/guidelines/IMM/IMM-guideline.pdf>
- CPSP FCPS-II guidelines. The major-subject guideline gives 100 MCQs in 2.5
  hours online, but radiology is not listed there. The minor-subject guideline
  defers the format to the prospectus and notification.
  <https://www.cpsp.edu.pk/files/guidelines/FCPS-IIa/FCPS-II-A-Major-guideline.pdf>,
  <https://www.cpsp.edu.pk/files/guidelines/FCPS-IIb/guideline.pdf>
- RCR Final FRCR Part A (CR2A). Two papers of 120 five-option SBAs, 3 hours each,
  across six areas. Marking is +1 for a correct answer and 0 for a wrong one (no
  negative marking). The pass mark is set per sitting by modified Angoff with
  Hofstee. <https://www.rcr.ac.uk/exams-training/rcr-exams/clinical-radiology-exams/frcr-part-2a-radiology-cr2a/frcr-part-2a-radiology-cr2a-guidance-notes-for-candidates/>
- RCR Final FRCR Part B (CR2B, from June 2025). Short cases: 25 radiographs in
  120 minutes (chest 50–60%, MSK 40–50%, abdomen up to 4%), each out of 5. Long
  cases: 6 cases in 75 minutes. Oral: 60 minutes with two examiner pairs and 12
  cases, marked by domain.
  <https://www.rcr.ac.uk/exams-training/rcr-exams/clinical-radiology-exams/frcr-part-2b-radiology-cr2b/frcr-part-2b-radiology-guidance-notes-for-candidates/>
- FRCR Part 1 (reference only, not a target): anatomy has 100 images in 90
  minutes, and physics is an MCQ module.
  <https://www.rcr.ac.uk/exams-training/rcr-exams/clinical-radiology-exams/frcr-part-1-radiology-cr1/>
- Unverified, left for the owner to set:
  - FCPS-II theory: current paper count, duration, and whether the SAQ paper
    still runs;
  - negative marking and pass marks for all CPSP papers (secondary sources say
    there is no negative marking);
  - TOACS station time (5 minutes per station assumed) and the IMM TOACS
    station count;
  - viva duration;
  - FRCR 2A per-area shares (equal shares assumed).

**Rejected.** Listing every subtopic in the per-chunk classifier prompt was
rejected: about 6k tokens per chunk across about 5,400 chunks. The merged prompt
may choose `max_level="topic"`. Storing topic codes in `curriculum_code` was also
rejected, because it would break every system-level reader. Recording owner
approval by editing the pack file was rejected too, because approval is
per-tenant and must be audited. No new dependencies.
