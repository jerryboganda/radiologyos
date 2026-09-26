<script lang="ts">
  import type { LoadProblem } from '$lib/api-state';
  import { capShare, formatTokens, formatUsd, STATUS_LABEL } from '$lib/admin-usage';
  import { percentFine } from '$lib/format';
  import type { EmbeddingUsage } from '$lib/types/admin';
  import LoadIssue from '../LoadIssue.svelte';
  import RerankUsage from './RerankUsage.svelte';
  import UsageAlerts from './UsageAlerts.svelte';

  let { usage, problem }: { usage: EmbeddingUsage | null; problem: LoadProblem | null } = $props();

  const FILL = { ok: 'bg-ok', amber: 'bg-warn', red: 'bg-danger' };
  const PILL = { ok: 'bg-ok-soft text-ok', amber: 'bg-warn-soft text-warn', red: 'bg-danger-soft text-danger' };
</script>

<p class="mt-1 mb-5 text-sm text-ink-2">Voyage API embeddings for your documents, measured against the free tier. Visible to admins only.</p>

{#if usage}
  {@const used = capShare(usage.tokens_used, usage.hard_cap_tokens)}
  {@const warn = capShare(usage.warn_tokens, usage.hard_cap_tokens)}
  <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
    <p class="text-sm text-ink-2">
      <span class="font-mono text-2xl font-semibold text-ink">{formatTokens(usage.tokens_used)}</span>
      of {formatTokens(usage.hard_cap_tokens)} tokens · {percentFine(used)}
    </p>
    <span class="rounded-full px-2 py-0.5 font-mono text-[0.6875rem] tracking-wide uppercase {PILL[usage.status]}">{STATUS_LABEL[usage.status]}</span>
  </div>
  <div
    class="relative mt-3 h-2.5 rounded-full bg-surface-2 ring-1 ring-line ring-inset"
    role="meter"
    aria-label="Embedding tokens used of the hard cap"
    aria-valuemin={0}
    aria-valuemax={usage.hard_cap_tokens}
    aria-valuenow={Math.min(usage.tokens_used, usage.hard_cap_tokens)}
    aria-valuetext="{formatTokens(usage.tokens_used)} of {formatTokens(usage.hard_cap_tokens)} tokens, warning at {formatTokens(usage.warn_tokens)}"
  >
    <div class="h-full rounded-full {FILL[usage.status]} {used > 0 ? 'min-w-1.5' : ''}" style:width="{used * 100}%"></div>
    <span class="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 rounded-full bg-ink" style:left="{warn * 100}%"></span>
  </div>
  <div class="relative mt-1.5 h-4 font-mono text-[0.6875rem] whitespace-nowrap text-muted" aria-hidden="true">
    <span class="absolute left-0">0</span>
    <span class="absolute -translate-x-full pr-1.5" style:left="{warn * 100}%">{formatTokens(usage.warn_tokens)} warn</span>
    <span class="absolute right-0">{formatTokens(usage.hard_cap_tokens)} cap</span>
  </div>

  <dl class="mt-6 grid gap-x-6 gap-y-5 sm:grid-cols-3">
    <div>
      <dt class="label">Free tier remaining</dt>
      <dd class="mt-1">
        <span class="font-mono text-lg text-ink">{formatTokens(usage.free_tier_remaining)}</span>
        <span class="text-sm text-muted">of {formatTokens(usage.free_tier_tokens)}</span>
      </dd>
    </div>
    <div>
      <dt class="label">Billed estimate</dt>
      <dd class="mt-1">
        <span class="font-mono text-lg {usage.billed_estimate_usd > 0 ? 'text-danger' : 'text-ink'}">{formatUsd(usage.billed_estimate_usd)}</span>
        <span class="block text-xs text-muted">Beyond the free tier; normally $0.00</span>
      </dd>
    </div>
    <div>
      <dt class="label">List-price equivalent</dt>
      <dd class="mt-1">
        <span class="font-mono text-lg text-ink">{formatUsd(usage.list_price_usd_equivalent)}</span>
        <span class="block text-xs text-muted">What this usage would cost at list price</span>
      </dd>
    </div>
  </dl>

  <dl class="mt-5 grid gap-x-6 gap-y-4 border-t border-line pt-5 sm:grid-cols-2">
    <div class="min-w-0">
      <dt class="label">Document model</dt>
      <dd class="mt-1">
        <span class="font-mono text-sm break-all text-ink">{usage.document_model}</span>
        <span class="block text-xs text-muted">Voyage API · counts toward the cap</span>
      </dd>
    </div>
    <div class="min-w-0">
      <dt class="label">Query model</dt>
      <dd class="mt-1">
        <span class="font-mono text-sm break-all text-ink">{usage.query_model}</span>
        <span class="block text-xs text-muted">Queries run locally — free</span>
      </dd>
    </div>
  </dl>

  <UsageAlerts alerts={usage.alerts} />
  {#if usage.rerank}<RerankUsage usage={usage.rerank} />{/if}
{:else if problem}
  <LoadIssue compact {problem} title="AI usage is unreachable" icon="signal" />
{/if}
