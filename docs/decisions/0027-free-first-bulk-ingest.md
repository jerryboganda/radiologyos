# 0027 — Free-first bulk ingest: text-first PDFs, Mistral, Claude fallback

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (Claude subscription routes), ADR 0012 (library pipeline), ADR 0021 (quota-aware effort)

**Context.** Reprocessing the library means reading about 6,900 pages and running
knowledge extraction and topic labelling over about 5,400 chunks. On the owner's
Claude Max subscription, that competes with their own daily usage. The owner
stated on 2026-09-26 that the library is public teaching material, so data
residency and training use are not a concern: quality and zero cost are.

**Decision.** The owner approved this on 2026-09-26.

1. **Text-first PDFs.** Before the vision pass on a PDF, `packages/library/text_first.py`
   keeps the stored native blocks and skips any model for pages that pass all of
   these checks:
   - pdf-inspector (a new MIT-licensed, local Rust dependency) finds a real,
     decodable text layer with no OCR need and no table;
   - pdfium finds no raster picture covering 2% or more of the page;
   - the page has at least 200 characters of native text.

   Any failure sends the page to vision. PowerPoint and Word files are not
   checked, because they would need a LibreOffice re-conversion for about 280
   full-text pages.
2. **Mistral first, Claude fallback.** A new top-level `agents:` map in
   `models.yaml` gives `page_parse`, `paper_topics`, `knowledge_extract`, and
   `topic_classify` the order Mistral `mistral-large-2512`, then Claude Opus 5.5.
   The gateway tries each target the transport serves. A failure, a usage limit,
   or schema-invalid output moves on to the next target. The Mistral transport
   (`packages/models/mistral.py`) runs on the owner's free Experiment plan,
   where training opt-in is required. It sends images inline, constrains output
   with the agent's JSON Schema (plain JSON mode if strict mode rejects it),
   paces itself to about one request per second, and retries short rate limits.
   `image_case`, the tutor, generation, grading, and the grounding and question
   checks stay on Claude.
3. Concrete names stay in `models.yaml`. The key is read only from
   `MISTRAL_API_KEY`, is saved by `infra/ops/set-mistral-key.sh` after a live
   check, and is never logged.

**Consequences.** Bulk ingest should draw little or no Claude quota. If Mistral's
monthly quota runs out, its output keeps failing validation, or the key is
missing, the work silently moves to Claude, and the owner's quota pays for it.
Watch the worker log. The plan to merge `knowledge_extract` and `topic_classify`
into one call was dropped, because both now run on the free tier. A 20-page
Mistral-versus-Claude comparison precedes the full reprocess, and any agent
whose Mistral output is not good enough moves back to Claude-first in
`models.yaml`.

**Rejected.**
- Gemini's free tier: too few requests per day for the current Flash models.
- OpenRouter, Groq, and GitHub Models free tiers: 50 to 1,000 requests a day and
  weaker vision models.
- Local OCR or vision models: the shared host has no GPU, and no local model
  reads radiology images well.
- New routes per backend: the four stable route names stay unchanged.
