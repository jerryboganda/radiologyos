<script lang="ts">
  import { formatDate, percent } from '$lib/format';
  import type { WeeklyReportOut } from '$lib/types/study';

  let { report }: { report: WeeklyReportOut | null } = $props();
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  let peak = $derived(Math.max(1, ...(report?.daily_minutes ?? [])));
  let retention = $derived(
    report?.retention.achieved === null || report?.retention.achieved === undefined
      ? 'No due reviews'
      : `${percent(report.retention.achieved)} of ${percent(report.retention.target)} target`
  );
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="report-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="report-heading" class="text-xl font-semibold text-ink">Weekly report</h2>
    {#if report}<p class="label">{formatDate(report.week_start)} – {formatDate(report.week_end)}</p>{/if}
  </div>
  {#if !report}
    <p class="mt-3 text-sm text-muted">Your first report is written on Monday morning, in your time zone, for the week just finished.</p>
  {:else}
    <dl class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div><dt class="label">Minutes</dt><dd class="font-display text-2xl text-ink tabular-nums">{report.minutes_studied}<span class="text-sm text-muted"> / {report.planned_minutes}</span></dd></div>
      <div><dt class="label">Reviews</dt><dd class="font-display text-2xl text-ink tabular-nums">{report.reviews}</dd></div>
      <div><dt class="label">Questions</dt><dd class="font-display text-2xl text-ink tabular-nums">{report.questions}{#if report.question_accuracy !== null}<span class="text-sm text-muted"> · {percent(report.question_accuracy)}</span>{/if}</dd></div>
      <div><dt class="label">Retention</dt><dd class="mt-1 text-sm text-ink">{retention}</dd></div>
    </dl>
    <div class="mt-4 flex h-16 items-end gap-1.5" role="img" aria-label="Minutes studied per day: {report.daily_minutes.join(', ')}">
      {#each report.daily_minutes as minutes, i (i)}
        <div class="flex flex-1 flex-col items-center gap-1">
          <div class="w-full rounded-sm bg-accent/70" style="height: {Math.round((minutes / peak) * 44)}px" title="{minutes} min"></div>
          <span class="font-mono text-[0.625rem] text-muted">{DAYS[i]}</span>
        </div>
      {/each}
    </div>
    <div class="mt-4 grid gap-4 sm:grid-cols-2">
      <div>
        <h3 class="label mb-1.5">Weakest systems</h3>
        {#if report.weakest.length === 0}<p class="text-sm text-muted">Add cards or questions to see this.</p>{/if}
        <ul class="space-y-1 text-sm text-ink-2">
          {#each report.weakest as system (system.code)}<li>{system.title} · <span class="font-mono text-xs">{percent(system.mastery)}</span> {system.band}</li>{/each}
        </ul>
      </div>
      <div>
        <h3 class="label mb-1.5">Next week's focus</h3>
        <ul class="space-y-1 text-sm text-ink-2">
          {#each report.focus as system (system.code)}<li>{system.title} <span class="text-muted">· {system.reason}</span></li>{/each}
        </ul>
      </div>
    </div>
    {#if report.notes.length}
      <ul class="mt-4 list-disc space-y-1 border-t border-line pt-3 pl-5 text-sm text-ink-2">
        {#each report.notes as note (note)}<li>{note}</li>{/each}
      </ul>
    {/if}
  {/if}
</section>
