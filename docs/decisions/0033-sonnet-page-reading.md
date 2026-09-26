# 0033 — Page reading on Claude Sonnet 5 high, Opus 5.5 on gate failure

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0010 (Claude subscription routes), ADR 0021 (quota-aware effort), ADR 0027 (free-first ingest)
- Supersedes: the Mistral part of ADR 0027

**Context.** Mistral's free plan turned out to be a $10-a-month credit, at zero
requests per minute until Studio is activated, and it doesn't offer Mistral
Large. The owner dropped Mistral on 2026-09-26. Page reading (`page_parse`, about
4,500 pages after text-first routing) is the largest draw on the owner's Max
subscription.

**Evidence.** Five real library pages (two PowerPoint slides, two text PDF pages,
and one image) were read with the same prompt and schema by each model:

| Model and effort | API-equivalent per page | Time | Text coverage (text pages) | Radiology figure found |
|---|---|---|---|---|
| Opus 5.5, low | $0.043 | 8.7 s | 96% / 98% | yes |
| Sonnet 5, low | $0.023 | 10.0 s | 96% / 97% | yes |
| Sonnet 5, high | $0.024 | 11.2 s | 96% / 97% | yes |

All three returned valid boxes, and Sonnet at high matched Opus's figure count.

**Decision.** The owner approved `page_parse` targets in this order:
1. `claude-sonnet-5` at `high`;
2. `claude-opus-5-5` at `medium`, used when Sonnet fails, hits a usage limit,
   or fails the ADR 0027 quality gates (under 80% text coverage, an empty
   reading of a text page, or out-of-range boxes).

Adaptive thinking keeps `high` almost as cheap as `low` on ordinary pages while
still allowing depth on hard ones. Other agents keep their route targets. The
Mistral transport code stays but is unused; its key was removed from the host.

**Consequences.** A library reprocess should draw roughly 55% of what Opus
at `low` would. A GPT-6 Luna (Codex) trial for knowledge extraction and
labelling is pending the owner's go-ahead.

**Rejected.**
- Opus 5.5 at `low` for every page: about 1.8 times the usage for the same
  measured quality.
- Sonnet 5 at `low`: only 3% cheaper than `high`, with less headroom on hard
  pages.
- Mistral Small or Medium: blocked by the $10 credit and zero-rate limit.
