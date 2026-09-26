<script lang="ts">
  import { percent } from '$lib/format';
  import { summaryLine } from '$lib/session';
  import type { SessionSummary } from '$lib/types/session';

  let { summary }: { summary: SessionSummary | null } = $props();
  let stats = $derived(
    summary
      ? [
          ['Steps done', `${summary.steps_done}/${summary.steps_total}`],
          ['Cards reviewed', String(summary.reviews)],
          ['SBA correct', summary.sba_answered ? `${summary.sba_correct}/${summary.sba_answered}` : '—'],
          ['Weighted coverage', percent(summary.weighted_coverage)]
        ]
      : []
  );
</script>

<div class="rounded-xl border border-ok/30 bg-ok-soft p-5" role="status">
  <p class="font-display text-xl text-ink">Today’s session is complete.</p>
  {#if summary}
    <p class="mt-1 text-sm text-ink-2">{summaryLine(summary)}</p>
    <dl class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {#each stats as [label, value] (label)}
        <div class="rounded-lg bg-surface px-3 py-2">
          <dt class="label">{label}</dt>
          <dd class="mt-0.5 font-display text-2xl text-ink tabular-nums">{value}</dd>
        </div>
      {/each}
    </dl>
  {/if}
  <p class="mt-4 text-sm text-ink-2">
    Tomorrow’s plan is rebuilt tonight from today’s results. Missed questions come back within two days.
    <a class="link" href="/progress">See progress</a>
  </p>
</div>
