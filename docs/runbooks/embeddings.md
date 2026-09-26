# Embeddings runbook — cost, usage, and the 195M hard stop (ADR 0019)

## What costs money

| Work | Where it runs | Cost |
| --- | --- | --- |
| Embedding document chunks and figure descriptions | Voyage API, `voyage-4-large` | Free inside 200M tokens per account |
| Search, tutor and question-topic queries | Local `voyage-4-nano` (`embedder` container) | $0 |
| Question-stem duplicate checks | Local `voyage-4-nano` | $0 |

**Estimate for the owner's library (September 2026):**
- 393 sources, about 9–10M characters of final text, roughly **2.3–2.8M tokens**.
- Figure descriptions add about 0.5M tokens.
- Total: **about 3.3M tokens once**, about $0.40 at list price. **Billed: $0.00**, because
  that is under 2% of the free tier.
- Queries are never billed.

## Why tokens are only paid once

- **Content cache.** Every text is hashed after normalisation (whitespace collapsed, a
  heading never repeated). `embedding_cache` holds one vector per hash, per tenant and
  model, and only cache misses are sent to Voyage.
- **Final text only.** Embedding waits while the Claude vision pass is still pending for a
  source, so pre-vision text is never paid for and then thrown away.
- **Progress is kept.** Each paid batch (up to about 100K tokens) is committed straight
  away with its ledger entry, so a crash or retry never re-pays.
- **Reprocess is selective.** `--reprocess` re-queues only jobs with work left.

**Cheapest order of operations:**
1. Add `CLAUDE_CODE_OAUTH_TOKEN` and let the vision pass finish.
2. Add `VOYAGE_API_KEY`.
3. Run `python -m apps.worker.app.ingest.bulk --subject "$SUBJECT" --reprocess` in the
   worker.

## Watching usage

- **Admins:** Settings → **AI usage** shows tokens used, the 150M warning line, the 195M
  cap, free-tier remaining, and the billed estimate.
- **API:** `GET /v1/admin/embedding-usage` (org_admin or superadmin only).
- **Worker logs:** carry counts only, for example
  `docker logs radiologyos-worker-1 2>&1 | grep "embedded source="`.

## At 150M and 195M tokens

- **150M: amber alert.** Admins get a push notification and a banner. Nothing stops.
- **195M: red alert.** No further Voyage request is sent. New sources stay
  keyword-searchable, and their `embed_index` step reads `skipped` /
  `embedding_budget_exhausted`. Queries keep working, because they run locally.
- **Acknowledging an alert** hides its banner. It does not raise the cap.
- **Raising the cap** is deliberate: edit `packages/models/models.yaml` (`budget:`), amend
  ADR 0019, deploy, then run `--reprocess`.

## The local embedder

- **Health:** `docker exec radiologyos-api-1 python -c "import urllib.request as u;
  print(u.urlopen('http://radbrain-embedder:8080/health').read())"`
- **If it is down:** search falls back to keyword-only and nothing fails. Restart it with
  `docker compose --env-file app.env -f platform.yml up -d embedder`.

## Keys

`VOYAGE_API_KEY` lives only in `/opt/radiologyos/app.env` (mode 600). Rotate it in the
Voyage dashboard and replace the value, then restart `api` and `worker`. No re-embedding
is needed.
