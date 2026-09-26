<script lang="ts">
  import type { LoadProblem } from '$lib/api-state';
  import { formatTokens, formatUsd } from '$lib/admin-usage';
  import { formatDate, percent } from '$lib/format';
  import { byAgent, openAlerts, successRate, windowExhausted } from '$lib/model-usage';
  import type { ModelUsage } from '$lib/types/admin';
  import AlertAck from '../AlertAck.svelte';
  import LoadIssue from '../LoadIssue.svelte';

  let { usage, problem }: { usage: ModelUsage | null; problem: LoadProblem | null } = $props();
  let agents = $derived(usage ? byAgent(usage.rows) : []);
  let alerts = $derived(usage ? openAlerts(usage) : []);
</script>

<p class="mt-1 mb-5 text-sm text-ink-2">
  Every model call in the last {usage?.window_days ?? 14} days, by agent. Counts only: prompts and answers are never recorded.
</p>

{#if usage}
  {#if windowExhausted(usage)}
    <p class="mb-4 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn" role="status">
      {usage.usage_limit_last_hour} call{usage.usage_limit_last_hour === 1 ? '' : 's'} hit the subscription usage limit in the last hour. Ingest and generation pause and resume
      when the window resets.
    </p>
  {/if}
  {#each alerts as alert (alert.id)}
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn/40 px-4 py-3">
      <div>
        <p class="text-sm font-medium text-ink">Usage-limit errors spiked</p>
        <p class="label mt-0.5">Raised {formatDate(alert.created_at)}</p>
      </div>
      <AlertAck ids={[alert.id]} />
    </div>
  {/each}

  <dl class="grid gap-x-6 gap-y-5 sm:grid-cols-4">
    <div>
      <dt class="label">Calls</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{usage.calls}</dd>
    </div>
    <div>
      <dt class="label">Succeeded</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{percent(successRate(usage))}</dd>
    </div>
    <div>
      <dt class="label">Usage-limit pauses</dt>
      <dd class="mt-1 font-mono text-lg {usage.usage_limit > 0 ? 'text-warn' : 'text-ink'}">{usage.usage_limit}</dd>
    </div>
    <div>
      <dt class="label">API-price equivalent</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{formatUsd(usage.cost_usd)}</dd>
    </div>
  </dl>

  {#if agents.length}
    <div class="mt-6 overflow-x-auto">
      <table class="w-full text-left text-sm">
        <caption class="sr-only">Model calls by agent</caption>
        <thead class="label">
          <tr><th class="py-2 pr-4 font-normal">Agent</th><th class="py-2 pr-4 text-right font-normal">Calls</th><th
              class="py-2 pr-4 text-right font-normal">Failed</th
            ><th class="py-2 pr-4 text-right font-normal">Limit</th><th class="py-2 text-right font-normal">Tokens</th></tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each agents as agent (agent.agent)}
            <tr>
              <td class="py-2 pr-4 font-mono break-all text-ink">{agent.agent}</td>
              <td class="py-2 pr-4 text-right font-mono">{agent.calls}</td>
              <td class="py-2 pr-4 text-right font-mono">{agent.failures}</td>
              <td class="py-2 pr-4 text-right font-mono">{agent.usageLimit}</td>
              <td class="py-2 text-right font-mono">{formatTokens(agent.tokens)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <p class="mt-5 text-sm text-muted">No model calls recorded in this window yet.</p>
  {/if}
{:else if problem}
  <LoadIssue compact {problem} title="Model usage is unreachable" icon="signal" />
{/if}
