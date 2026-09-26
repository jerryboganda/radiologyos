<script lang="ts">
  import { calibrationText, formatSeconds } from '$lib/exam-review';
  import type { ExamReview } from '$lib/types/results';

  let { review, numbers }: { review: ExamReview; numbers: Map<string, number> } = $props();
  let timing = $derived(review.timing);
  let cal = $derived(review.calibration);
  const pct = (value: number | null) => (value === null ? '—' : `${Math.round(value * 100)}%`);
</script>

<section class="grid gap-4 lg:grid-cols-2" aria-label="Results review">
  <div class="panel p-5">
    <h2 class="text-lg font-semibold text-ink">Time per item</h2>
    {#if timing.timed_items}
      <p class="mt-1 text-sm text-ink-2">
        {formatSeconds(timing.total_seconds)} on {timing.timed_items} item{timing.timed_items === 1 ? '' : 's'} · median
        {formatSeconds(timing.median_seconds)} · mean {formatSeconds(timing.mean_seconds)}
      </p>
      {#if timing.slowest.length}
        <p class="label mt-3">Slowest</p>
        <ul class="mt-1 flex flex-wrap gap-2">
          {#each timing.slowest as slow (slow.question_id)}
            <li>
              <a class="rounded-lg border border-line px-2.5 py-1 font-mono text-xs text-ink-2 hover:border-accent" href="#item-{numbers.get(slow.question_id)}">
                Q{numbers.get(slow.question_id) ?? '?'} · {formatSeconds(slow.seconds)}
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {:else}
      <p class="mt-1 text-sm text-muted">No time was recorded for this exam.</p>
    {/if}
  </div>
  <div class="panel p-5">
    <h2 class="text-lg font-semibold text-ink">Confidence calibration</h2>
    <p class="mt-1 text-sm text-ink-2">{calibrationText(cal)}</p>
    {#if cal.rated}
      <table class="mt-3 w-full text-left text-sm">
        <thead class="label"><tr><th class="py-1 font-normal">Confidence</th><th class="py-1 font-normal">Items</th><th class="py-1 font-normal">Stated</th><th class="py-1 font-normal">Scored</th></tr></thead>
        <tbody class="divide-y divide-line">
          {#each cal.levels as level (level.level)}
            <tr>
              <td class="py-1.5 text-ink capitalize">{level.label}</td>
              <td class="py-1.5 font-mono text-xs text-ink-2">{level.count}</td>
              <td class="py-1.5 font-mono text-xs text-ink-2">{pct(level.stated)}</td>
              <td class="py-1.5 font-mono text-xs text-ink">{pct(level.mean_score)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p class="mt-2 text-xs text-muted">
        {cal.confidently_wrong} confidently wrong · {cal.unsure_right} right when unsure. Calibration is shown on its own and never changes your score.
      </p>
    {/if}
  </div>
</section>
