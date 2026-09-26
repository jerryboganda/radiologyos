<script lang="ts">
  import Notice from '$lib/components/Notice.svelte';
  import { calibrationCopy, pct, projectionCopy } from '$lib/heatmap';
  import type { Calibration, Projection } from '$lib/types/session';

  let { projection, calibration }: { projection: Projection; calibration: Calibration } = $props();
  let pace = $derived(projectionCopy(projection));
  let cal = $derived(calibrationCopy(calibration));
  let bar = $derived(Math.round(Math.min(Math.max(projection.coverage, 0), 1) * 100));
  let projected = $derived(projection.projected_coverage === null ? null : Math.round(projection.projected_coverage * 100));
</script>

<div class="grid gap-6 lg:grid-cols-2">
  <section class="panel p-5" aria-labelledby="pace-heading">
    <h2 id="pace-heading" class="text-xl font-semibold text-ink">Days remaining and pace</h2>
    <p class="label mt-1">{projection.days_remaining} days to the exam · goal {pct(projection.goal)} weighted coverage by {projection.target_days} days from now</p>
    <div
      class="relative mt-4 h-3 overflow-hidden rounded-full bg-surface-2"
      role="img"
      aria-label="Weighted coverage now {bar}%{projected === null ? '' : `, projected ${projected}% by exam day`}"
    >
      {#if projected !== null}<div class="absolute inset-y-0 left-0 bg-ok/30" style="width: {projected}%"></div>{/if}
      <div class="absolute inset-y-0 left-0 bg-ok" style="width: {bar}%"></div>
    </div>
    <p class="mt-1 flex justify-between font-mono text-xs text-muted"><span>now {bar}%</span>{#if projected !== null}<span>exam day {projected}%</span>{/if}</p>
    <div class="mt-4"><Notice tone={pace.tone}><strong>{pace.headline}.</strong> {pace.detail}</Notice></div>
    <dl class="mt-4 grid grid-cols-2 gap-3 text-sm">
      <div><dt class="label">Recent pace</dt><dd class="text-ink">{projection.minutes_per_day === null ? '—' : `${Math.round(projection.minutes_per_day)} min/day`}</dd></div>
      <div><dt class="label">Needed</dt><dd class="text-ink">{projection.needed_minutes_per_day === null ? '—' : `${Math.round(projection.needed_minutes_per_day)} min/day`}</dd></div>
      <div><dt class="label">Weighted topics left</dt><dd class="text-ink">{projection.topics_remaining} ({pct(projection.remaining_weighted)} of weight)</dd></div>
      <div><dt class="label">Sessions measured</dt><dd class="text-ink">{projection.sessions_in_window} in 28 days</dd></div>
    </dl>
  </section>

  <section class="panel p-5" aria-labelledby="calibration-heading">
    <h2 id="calibration-heading" class="text-xl font-semibold text-ink">Confidence calibration</h2>
    <p class="label mt-1">{calibration.rated} rated SBA answers in 90 days · tracked apart from mastery</p>
    <div class="mt-4"><Notice tone={cal.tone}><strong>{cal.headline}.</strong> {cal.detail}</Notice></div>
    <table class="mt-4 w-full text-left text-sm">
      <caption class="sr-only">Accuracy by self-rated confidence</caption>
      <thead class="label border-b border-line">
        <tr><th scope="col" class="py-2 font-normal">Confidence</th><th scope="col" class="py-2 font-normal">Answers</th><th scope="col" class="py-2 font-normal">Right</th><th scope="col" class="py-2 font-normal">Expected</th></tr>
      </thead>
      <tbody class="divide-y divide-line">
        {#each calibration.levels as level (level.level)}
          <tr>
            <th scope="row" class="py-2 font-normal text-ink capitalize">{level.label}</th>
            <td class="py-2 font-mono text-xs text-ink-2">{level.answers}</td>
            <td class="py-2 font-mono text-xs text-ink-2">{pct(level.accuracy)}</td>
            <td class="py-2 font-mono text-xs text-muted">{pct(level.stated)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
</div>
