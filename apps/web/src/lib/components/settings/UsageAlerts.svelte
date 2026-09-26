<script lang="ts">
  import { ALERT_TITLE, sortAlerts } from '$lib/admin-usage';
  import { formatDate } from '$lib/format';
  import type { UsageAlert } from '$lib/types/admin';
  import AlertAck from '../AlertAck.svelte';

  let { alerts }: { alerts: UsageAlert[] } = $props();
  let sorted = $derived(sortAlerts(alerts));
  const PILL = { red: 'bg-danger-soft text-danger', amber: 'bg-warn-soft text-warn' };
</script>

<h3 class="label mt-7 mb-3">Alert history</h3>
{#if sorted.length}
  <ul class="divide-y divide-line rounded-xl border border-line" aria-label="Embedding budget alerts">
    {#each sorted as alert (alert.id)}
      <li class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div class="flex min-w-0 items-start gap-3">
          <span class="mt-0.5 shrink-0 rounded-full px-2 py-0.5 font-mono text-[0.6875rem] tracking-wide uppercase {PILL[alert.level]}"
            >{alert.level}</span
          >
          <div class="min-w-0">
            <p class="text-sm font-medium text-ink">{ALERT_TITLE[alert.level]}</p>
            <p class="label mt-0.5">
              Raised {formatDate(alert.created_at)} · {alert.acknowledged_at ? `acknowledged ${formatDate(alert.acknowledged_at)}` : 'not acknowledged'}
            </p>
          </div>
        </div>
        {#if !alert.acknowledged_at}<AlertAck ids={[alert.id]} />{/if}
      </li>
    {/each}
  </ul>
{:else}
  <p class="text-sm text-muted">No alerts yet. Amber fires at the warning threshold, red at the hard cap.</p>
{/if}
