# 0012 — Durable library pipeline, backend-for-frontend auth, and new dependencies

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0001 (RLS), ADR 0010 (models), ADR 0011 (personal-first)

The in-memory preview library is replaced for real use by a durable pipeline.
Migration `20260926_0004` adds `source_pages`, `source_blocks`, `figures`, and
`chunks` (tsvector plus `vector(1024)`), each with ENABLE+FORCE RLS and a
two-tenant runtime-role proof (`evals/checks/test_library_live.py`). Uploads
stream through the API into private object storage under
`tenants/<tenant>/sources/<source>/`, DICOM is refused by content, and a Celery
job runs resumable steps recorded in `job_steps`: render pages with native text
first (searchable within minutes), then an Opus 5.5 vision pass per page
(`page_parse`, medium effort) and per radiology figure (`image_case`, high
effort), re-chunking and Voyage embedding as keys allow; a subscription
usage-limit pause defers the job instead of failing it. Search fuses tsvector
and pgvector rankings with RRF (k=60) and returns source/page/block citations.
Private storage is not browser-reachable, so page and figure images stream
through authenticated API routes. The web server calls the API as the user by
signing a 60-second HS256 assertion carrying only the OIDC subject with
`WEB_API_SECRET` (shared by web and API, never the browser); the API resolves
tenant and role from the membership table exactly as for an OIDC token.
**New dependencies (owner authorised):** `boto3` (S3/MinIO client),
`pypdfium2` (Apache/BSD PDF rendering, chosen over AGPL PyMuPDF), `pillow`
(image crop), `types-PyYAML` (dev typing), LibreOffice in the Python image
(DOCX/PPTX to PDF), and the Claude Code CLI native binary copied from a Node
build stage (no Node at runtime). The worker's limits rise to 2 CPUs / 3 GB for
LibreOffice and rendering.
