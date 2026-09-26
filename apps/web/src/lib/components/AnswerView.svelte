<script lang="ts">
  import {
    GROUNDING_LABEL,
    SUPPORT_LABEL,
    type Grounding,
    type JudgeStats,
    type Segment,
    type TutorCitation
  } from '$lib/types/tutor';
  import CitationChip from './CitationChip.svelte';
  import FigureChip from './FigureChip.svelte';

  let {
    segments,
    grounding,
    fallback = '',
    dropped = 0,
    judge = null
  }: {
    segments: Segment[];
    grounding: Grounding | null;
    fallback?: string;
    dropped?: number;
    judge?: JudgeStats | null;
  } = $props();

  const figures = (citations: TutorCitation[]) => citations.filter((c) => c.kind === 'figure');
  const others = (citations: TutorCitation[]) => citations.filter((c) => c.kind !== 'figure');
  let removed = $derived(Math.max(dropped, judge?.unsupported ?? 0));

  function judgeSummary(stats: JudgeStats | null): string {
    if (!stats) return '';
    if (stats.status === 'ok') return ` · ${stats.judged} checked against their citations`;
    if (stats.status === 'failed') return ' · citation check unavailable';
    if (stats.status === 'skipped') return ' · citation check switched off';
    return '';
  }
</script>

{#snippet support(segment: Segment)}
  {#if segment.support === 'partial' || segment.support === 'not_verified'}
    <span
      class="mr-1.5 inline-block rounded border px-1.5 py-px align-middle font-mono text-[0.625rem] tracking-wide uppercase {segment.support ===
      'partial'
        ? 'border-warn/40 bg-warn-soft text-warn'
        : 'border-line bg-surface-2 text-muted'}"
      title={segment.support_note ?? SUPPORT_LABEL[segment.support]}>{SUPPORT_LABEL[segment.support]}</span
    >
  {/if}
{/snippet}

{#snippet chips(segment: Segment)}
  {#each others(segment.citations) as citation, j (j)}<span class="ml-1 inline-block"><CitationChip {citation} /></span>{/each}
  {#if figures(segment.citations).length}
    <span class="mt-1.5 flex flex-wrap gap-1.5">
      {#each figures(segment.citations) as citation, j (j)}<FigureChip {citation} />{/each}
    </span>
  {/if}
{/snippet}

<div class="panel p-4 sm:p-5">
  {#if segments.length === 0}
    <p class="text-sm text-ink-2">{fallback || 'No grounded answer was found in your sources.'}</p>
  {/if}
  <div class="flex flex-col gap-3">
    {#each segments as segment, i (i)}
      {#if segment.origin === 'web'}
        <div class="rounded-xl border border-web/30 bg-web-soft/60 p-3">
          <p class="label !text-web">From the web · not from your library</p>
          <p class="mt-1 text-[0.9375rem] leading-relaxed text-ink">{@render support(segment)}{segment.text}</p>
          <div class="mt-2 flex flex-wrap gap-1.5">
            {#each segment.citations as citation, j (j)}<CitationChip {citation} />{/each}
          </div>
        </div>
      {:else}
        <p class="text-[0.9375rem] leading-relaxed text-ink">
          {@render support(segment)}{segment.text}
          {@render chips(segment)}
        </p>
      {/if}
    {/each}
  </div>
  <p class="label mt-4 border-t border-line pt-3">
    {grounding ? GROUNDING_LABEL[grounding] : 'Answer'}{judgeSummary(judge)}{removed > 0
      ? ` · ${removed} unverifiable sentence${removed === 1 ? '' : 's'} removed`
      : ''}
  </p>
</div>
