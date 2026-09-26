<script lang="ts">
  import { capShare, formatTokens, formatUsd, RERANK_ALERT_TITLE, STATUS_LABEL } from '$lib/admin-usage';
  import { percentFine } from '$lib/format';
  import type { RerankUsage } from '$lib/types/admin';
  import UsageAlerts from './UsageAlerts.svelte';

  // The reranker's own free tier and hard cap (ADR 0028), shown next to embeddings.
  let { usage }: { usage: RerankUsage } = $props();

  const FILL = { ok: 'bg-ok', amber: 'bg-warn', red: 'bg-danger' };
  const PILL = { ok: 'bg-ok-soft text-ok', amber: 'bg-warn-soft text-warn', red: 'bg-danger-soft text-danger' };
  let used = $derived(capShare(usage.tokens_used, usage.hard_cap_tokens));
  let warn = $derived(capShare(usage.warn_tokens, usage.hard_cap_tokens));
</script>

<section class="mt-6 border-t border-line pt-5" aria-labelledby="rerank-usage-heading">
  <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
    <div class="min-w-0">
      <h3 id="rerank-usage-heading" class="label">Reranking · <span class="font-mono normal-case">{usage.model}</span></h3>
      <p class="mt-1 text-sm text-ink-2">
        <span class="font-mono text-lg font-semibold text-ink">{formatTokens(usage.tokens_used)}</span>
        of {formatTokens(usage.hard_cap_tokens)} tokens · {percentFine(used)}
      </p>
    </div>
    <span class="rounded-full px-2 py-0.5 font-mono text-[0.6875rem] tracking-wide uppercase {PILL[usage.status]}"
      >{usage.status === 'red' ? 'Reranking stopped' : STATUS_LABEL[usage.status]}</span
    >
  </div>
  <div
    class="relative mt-3 h-2 rounded-full bg-surface-2 ring-1 ring-line ring-inset"
    role="meter"
    aria-label="Rerank tokens used of the hard cap"
    aria-valuemin={0}
    aria-valuemax={usage.hard_cap_tokens}
    aria-valuenow={Math.min(usage.tokens_used, usage.hard_cap_tokens)}
    aria-valuetext="{formatTokens(usage.tokens_used)} of {formatTokens(usage.hard_cap_tokens)} tokens, warning at {formatTokens(usage.warn_tokens)}"
  >
    <div class="h-full rounded-full {FILL[usage.status]} {used > 0 ? 'min-w-1.5' : ''}" style:width="{used * 100}%"></div>
    <span class="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 rounded-full bg-ink" style:left="{warn * 100}%"></span>
  </div>
  <p class="mt-2 text-xs text-muted">
    Separate free tier: {formatTokens(usage.free_tier_remaining)} of {formatTokens(usage.free_tier_tokens)} left · billed
    estimate {formatUsd(usage.billed_estimate_usd)} · list-price equivalent {formatUsd(usage.list_price_usd_equivalent)}. Past the cap,
    search keeps its fused order.
  </p>
  <UsageAlerts alerts={usage.alerts} label="Rerank budget alerts" titles={RERANK_ALERT_TITLE} />
</section>
