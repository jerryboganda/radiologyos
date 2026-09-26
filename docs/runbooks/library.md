# Library runbook — upload, ingestion, AI parsing, search

Status: implemented (ADR 0012). Personal-first (ADR 0011).

## How a source flows

1. **Upload** (web Library page, or the bulk importer). Content is sniffed, DICOM is
   refused, the file is hashed (duplicates return the existing source), stored at
   `tenants/<tenant>/sources/<source>/original.<ext>` in private object storage, and
   a `jobs` row plus an audit entry are written. The job is queued on Redis.
2. **Worker** (`radbrain.ingest_source`), steps recorded in `job_steps`:
   `render_pages` (150 dpi PNG + native text blocks per page; DOCX/PPTX via
   LibreOffice) → `chunk` → `embed_index` (Voyage, skipped without a key) →
   `ready_notify` (the source is searchable now) → `parse_layout` + `extract_figures`
   (Opus 5.5 `page_parse` per page at medium effort; `image_case` per radiology figure
   at high effort; skipped without a model token) → re-chunk and re-embed →
   `knowledge_extraction` left `pending` for the knowledge worker.
3. A subscription usage-limit error **defers** the job 30 minutes (`INGEST_DEFER_SECONDS`)
   and it resumes from the next unparsed page. Re-running a job is always safe.

## Enable the AI parsing and embeddings (owner, one time)

On a machine where you are logged in to Claude Code with the Max subscription:

```bash
claude setup-token          # opens a browser; prints a 1-year token
```

Then on the VPS (`ssh vps`), add both values to `/opt/radiologyos/app.env`
(mode 600; never commit or paste them anywhere else):

```bash
CLAUDE_CODE_OAUTH_TOKEN=<token from claude setup-token>
VOYAGE_API_KEY=<key from dashboard.voyageai.com>   # see embeddings.md: cost, 195M hard stop
```

Apply without a code deploy, then resume every job so pending pages get parsed:

```bash
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml up -d worker api
docker compose --env-file app.env -f platform.yml exec -T worker \
  python -m apps.worker.app.ingest.bulk --subject "$SUBJECT" --reprocess
```

The token is only ever read by the worker process; it is never logged, stored in
the database, or sent to the browser. Subscription use covers the owner's own
tenant only (ADR 0010).

## Bulk import from the VPS

Large files cannot go through Cloudflare (100 MB request limit), so bulk material is
copied to `/opt/radiologyos/import` (mode 700, root only) and imported server side:

```bash
. /opt/radiologyos/keycloak/subject.env     # KEYCLOAK_BOOTSTRAP_SUBJECT
cd /opt/radiologyos
docker compose --env-file app.env -f platform.yml run --rm -T \
  -v /opt/radiologyos/import:/import:ro worker \
  python -m apps.worker.app.ingest.bulk --subject "$KEYCLOAK_BOOTSTRAP_SUBJECT" --dir /import
```

It prints only source/job ids and counts. Re-running skips files already imported.

## Checking progress

```bash
docker logs --since 10m radiologyos-worker-1 | grep -E "ingest job=|page_parse failed"
```

The Library page shows per-source step status. `pages_parsed` counts pages that
finished the vision pass.

## Deleting

Deleting a source removes its rows (cascade: pages, blocks, figures, chunks, jobs)
and every object under its storage prefix, and writes an audit entry.

Embedding cost, the local query model, and the 195M-token hard stop are in
[`embeddings.md`](embeddings.md) (ADR 0019).
