<script lang="ts">
  import CitationList from '$lib/components/CitationList.svelte';
  import type { VivaDebrief } from '$lib/types/viva';
  import { percentOf, STAGE_LABELS, STOP_REASONS, type Stage } from '$lib/viva';

  let { debrief, kind }: { debrief: VivaDebrief; kind: string } = $props();
  const width = (percent: number | null) => `width:${Math.max(0, Math.min(100, percent ?? 0))}%`;
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="debrief-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="debrief-heading" class="text-xl font-semibold text-ink">Debrief</h2>
    <p class="font-mono text-sm text-ink-2">{STOP_REASONS[debrief.stop_reason] ?? debrief.stop_reason}</p>
  </div>
  <p class="mt-3 font-display text-4xl text-ink">{debrief.overall_percent}%</p>
  <p class="text-sm text-muted">
    {debrief.turns_answered} answer{debrief.turns_answered === 1 ? '' : 's'} marked{kind === 'viva' && debrief.level_reached
      ? ` · reached level ${debrief.level_reached} of 5`
      : ''}. Scores come from your sources' marking points, not the model's opinion.
  </p>

  <ul class="mt-5 grid gap-3 sm:grid-cols-3" aria-label="Scores by competency">
    {#each debrief.competencies as competency (competency.key)}
      <li>
        <p class="flex justify-between text-sm">
          <span class="text-ink">{competency.label}</span>
          <span class="font-mono text-ink-2">{competency.percent === null ? '—' : `${competency.percent}%`}</span>
        </p>
        <div class="mt-1 h-2 overflow-hidden rounded-full bg-surface-2" role="presentation">
          <div class="h-full rounded-full bg-accent" style={width(competency.percent)}></div>
        </div>
      </li>
    {/each}
  </ul>

  {#if debrief.stages.length}
    <table class="mt-5 w-full text-sm">
      <caption class="label text-left">Score per stage</caption>
      <tbody>
        {#each debrief.stages as stage (stage.stage)}
          <tr class="border-b border-line">
            <th scope="row" class="py-1.5 text-left font-normal text-ink">{STAGE_LABELS[stage.stage as Stage] ?? stage.stage}</th>
            <td class="py-1.5 text-right font-mono text-ink-2">{stage.score} / {stage.max_score} ({percentOf(stage.score, stage.max_score)}%)</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if debrief.teaching_points.length}
    <h3 class="mt-6 font-semibold text-ink">Teaching points</h3>
    <ul class="mt-2 flex flex-col gap-3">
      {#each debrief.teaching_points as point, i (i)}
        <li class="rounded-lg border-l-2 pl-3 {point.verdict === 'good' ? 'border-ok' : 'border-warn'}">
          <p class="text-[0.9375rem] leading-relaxed text-ink">{point.text}</p>
          <CitationList citations={point.citations} class="mt-1" />
        </li>
      {/each}
    </ul>
  {/if}
  {#if debrief.weak_areas}
    <p class="mt-4 text-sm text-muted">{debrief.weak_areas} weak area{debrief.weak_areas === 1 ? '' : 's'} identified; revisit the cited pages above.</p>
  {/if}
</section>
