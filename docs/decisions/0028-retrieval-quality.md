# 0028 — Retrieval quality: Voyage reranker, graph expansion, intent routing

- Status: accepted (implementation; production eval of the reranker pending)
- Date: 2026-09-26
- Related: ADR 0013 (grounded tutor), ADR 0016 (knowledge graph), ADR 0019
  (embedding cost policy), ADR 0025 (tutor depth), completion plan G13

**Reranker (owner-approved concrete model).** After RRF fusion, library search,
tutor retrieval, and question/viva retrieval send up to `candidates` (24) fused hits
to Voyage `rerank-2.5` (`POST /v1/rerank`, httpx, key from `VOYAGE_API_KEY`), keep at
most the caller's limit, and drop hits scored below `min_score` (0.2); the config is
the new strict `rerank:` block in `models.yaml` (`RerankConfig`). Voyage's free tier
is 200M tokens *per model*, so the reranker has its own lifetime cap (195M hard,
150M warn): its tokens go into the existing `embedding_usage` ledger under the model
name, migration `20260926_0101` adds the SECURITY DEFINER
`app.voyage_model_tokens_total(model)` (one number across tenants), and
`app.embedding_tokens_total()` now excludes `rerank*` models so neither cap eats
the other. Each call checks the cap first, estimates tokens as Voyage counts them
(query × documents + documents; documents are clipped to 4,000 characters),
records `usage.total_tokens` afterwards, and raises `rerank_budget` amber/red
`ops_alerts` (the kind CHECK was widened) with the same admin push and banner. It
**fails open**: without a key, past the cap, or on any provider or database error,
results keep their RRF order and nothing is raised into the request. The tutor
holds no transaction during the call. `GET /v1/admin/embedding-usage` gains a
`rerank` block shown under the embedding meter. **Graph expansion.** The concepts
whose active claims were extracted from the top 4 retrieved chunks seed a 1-hop walk
over `concept_edges` (at most 6–8 neighbours, relations preferred by intent, e.g.
`differential_of` for a DDx); at most 2 claims per concept and 6–8 in all (verified,
then important, first) are offered to `tutor_answer` as extra excerpts `K1..Kn`. The
excerpt text is the claim's verbatim **evidence span** (≤600 characters) and its
citation is the claim's chunk, source, pages, and blocks, so the citation check and
the grounding judge verify against source text, never the extracted paraphrase; a
claim without chunk, span, or pages is never offered, and claims on chunks already
retrieved are skipped. Every read is RLS-bound and scoped to the caller's own,
non-deleted sources. **Intent routing.** A deterministic keyword/regex classifier
(`packages/tutor/intent.py`, no model call, so no `classify` agent was needed) picks
`explain`, `compare` (also searches each named subject and keeps one hit per
subject), `ddx`, `show_me` (six figures instead of four), `report`, or `quiz`
(no retrieval and no model call: the answer is a hand-off to question generation,
`/questions?topic=`). The intent reaches the new prompt `tutor_answer/v4` (v3 kept)
as a non-citable `<intent>` block; v4 may lay a segment out under a `section` or as a
table cell (`row` + `column`: a comparison table or a differential list with
discriminators), and every cell is still a cited, judged segment. The intent is
stored in the answer's `citations` array (`{"kind": "intent"}`), returned on the
ask and thread routes, and the web tutor renders headings and tables. Trade-offs:
reranking adds one ~0.3 s network call and ~10–20K tokens per search (about 10,000
searches fit the free tier); regex routing will misroute unusual phrasings (the
answer is still grounded, only shaped differently). Proofs:
`apps/api/tests/test_rerank.py`, `test_tutor_intent.py`, `test_tutor_graph.py`,
`test_tutor_routing_api.py`, and the runtime-role live proof
`evals/checks/test_rerank_budget_live.py`; eval cases `evals/fixtures/tutor_v4.json`.
Runbooks: `docs/runbooks/tutor.md`, `docs/runbooks/embeddings.md`.
