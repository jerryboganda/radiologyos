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

### Models, quality gates and approvals (ADR 0035, ADR 0036, ADR 0037)

- **Free first.** PDF, PPTX and DOCX pages with a good text layer keep their native
  text and make no model call. PPTX and DOCX are checked through the LibreOffice PDF.
  The worker logs `text_first ... native_pages=N vision_pages=M`.
- **The owner's final flow for all bulk work** (pages, figures, knowledge):
  1. GPT-6 Luna at max reasoning.
  2. GPT-6 Sol at high when Luna fails or a quality gate finds its answer ambiguous.
  3. Claude Opus 5.5 high **only for items the owner approves**.

  The targets are in `agents:` in `packages/models/models.yaml`.
- **Quality gates:**
  - Pages: under 80% of the page's own words, an empty reading, or bad boxes.
  - Figures: an empty reading, or a "source" diagnosis whose quote is not on the page. A
    low-confidence reading only gets Sol's second opinion.
  - Knowledge chunks: too many claims without supporting evidence. A doubted source
    statement or context-free claims only get Sol's second opinion.
  - The worker logs `quality gate agent=... reason=... action=fallback|kept_last`.
- **Collect & ask.** Items neither GPT model answers well are saved in
  `model_escalations`, and the owner gets one alert. Pages and figures keep the best GPT
  reading meanwhile; knowledge chunks are held.

## Pause, resume, relaunch, approve (ADR 0037)

Every unit (a page, a figure page, a knowledge chunk) is saved as soon as it is done,
so the run can stop at any time and continue exactly where it stopped:

```bash
. /opt/radiologyos/keycloak/subject.env
cli() { docker exec radiologyos-worker-1 python -m apps.worker.app.ops.pipeline_cli           --subject "$KEYCLOAK_BOOTSTRAP_SUBJECT" "$@"; }
cli status      # pause state, pages/jobs/knowledge progress, items awaiting approval
cli pause       # stops model work between units on every worker
cli resume
cli relaunch    # re-queue every unfinished job and lost knowledge pass (safe any time)
cli approve     # the owner's OK: saved items are redone on Claude Opus 5.5 high
cli dismiss     # close saved items without using Claude
cli clear-quota # lift a ChatGPT quota pause early (the window has reset)
```

The same controls are on Settings for admins.
- When the ChatGPT quota runs out, every worker pauses until the reset time ChatGPT
  gave (or 30 minutes), and the owner gets one push notification. The work resumes by
  itself. A quota never falls through to Claude.
- `relaunch --redo-unchecked-figures` re-reads pages whose figures were described
  before ADR 0036.
- `relaunch --redo-old-knowledge` replaces claims written by an older extraction prompt.

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

## Tables (ADR 0030)

`extract_tables` runs with every chunk pass and needs no model. Each `table` block
the page parser wrote (rows as lines, cells separated by `" | "`) becomes a
`source_tables` row: cells, CSV, escaped HTML, and the block's bbox. The reader's
**Tables** tab shows them. Selecting one highlights its block on the page. Search
lists matching tables (tsvector) above the passages. The step's `output_ref` is
`tables:N`. Text that does not parse as a table stays an ordinary block.

## Re-process one source (ADR 0030)

In the reader, **Re-process** (`POST /v1/library/sources/{id}/reprocess`) is
available only to the source's uploader. Everyone else gets 404, and a job that is
running (updated in the last 2 hours) gets 409. It sets failed pages back to
`pending`, marks the latest ingest job `queued`, audits
`source.reprocess_requested`, and re-queues it. The pipeline then skips finished
steps and pages already parsed, and rebuilds chunks and tables from the stored
blocks. It embeds only text the embedding cache does not hold, so unchanged text
costs nothing. Knowledge units already done are skipped by content hash. To
re-queue every source that still has work, use the bulk `--reprocess` above.

## Deleting

Deleting a source removes its rows (cascade: pages, blocks, figures, chunks, jobs)
and every object under its storage prefix, and writes an audit entry.

Embedding cost, the local query model, and the 195M-token hard stop are in
[`embeddings.md`](embeddings.md) (ADR 0019).
