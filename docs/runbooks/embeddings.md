# Embeddings runbook — cost, usage, and the 195M hard stop (ADR 0019)

## What costs money

| Work | Where it runs | Cost |
| --- | --- | --- |
| Embedding document chunks and figure descriptions | Voyage API, `voyage-4-large` | Free inside 200M tokens per account |
| Search, tutor and question-topic queries | Voyage API, `voyage-4-large` (metered) | About 10–30 tokens each, free inside the quota |
| Question-stem duplicate checks | Voyage API, `voyage-4-large` (metered) | Tiny, free inside the quota |

The owner chose the paid best model for everything (ADR 0019 override). The local
`voyage-4-nano` embedder is kept but switched off.

**Estimate for the owner's library, measured in production (September 2026):**
- A real 12-chunk slide deck cost 378 tokens, about 2.3 characters per token. Slide
  fragments are abbreviation-heavy.
- 393 sources, about 7.2M characters of text today; about 9–10M after the vision pass.
- That is roughly **3–4.5M tokens**, plus up to about 1M for figure descriptions.
- Total: **about 5M tokens once at most**. That is about **2.5% of the 195M cap**, or about
  $0.60 at list price.
- **Billed: $0.00**, inside the free tier. Queries add well under 0.1% of the cap per month.

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
  `embedding_budget_exhausted`. Search and the tutor fall back to keyword-only.
- **Acknowledging an alert** hides its banner. It does not raise the cap.
- **Raising the cap** is deliberate: edit `packages/models/models.yaml` (`budget:`), amend
  ADR 0019, deploy, then run `--reprocess`.

## The local embedder (switched off)

To use it again: in `models.yaml` set `query: {backend: local, model: voyage-4-nano,
base_url: http://radbrain-embedder:8080}`, deploy, then start it with
`docker compose --env-file app.env -f platform.yml --profile embedder up -d embedder`.


- **Health:** `docker exec radiologyos-api-1 python -c "import urllib.request as u;
  print(u.urlopen('http://radbrain-embedder:8080/health').read())"`
- **If it is down:** search falls back to keyword-only and nothing fails. Restart it with
  `docker compose --env-file app.env -f platform.yml up -d embedder`.

## Keys

`VOYAGE_API_KEY` lives only in `/opt/radiologyos/app.env` (mode 600). Rotate it in the
Voyage dashboard and replace the value, then restart `api` and `worker`. No re-embedding
is needed.
