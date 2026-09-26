<script lang="ts">
  import { GROUNDING_LABEL, type Grounding, type Segment } from '$lib/types/tutor';
  import CitationChip from './CitationChip.svelte';

  let {
    segments,
    grounding,
    fallback = '',
    dropped = 0
  }: { segments: Segment[]; grounding: Grounding | null; fallback?: string; dropped?: number } = $props();
</script>

<div class="panel p-4 sm:p-5">
  {#if segments.length === 0}
    <p class="text-sm text-ink-2">{fallback || 'No grounded answer was found in your sources.'}</p>
  {/if}
  <div class="flex flex-col gap-3">
    {#each segments as segment, i (i)}
      {#if segment.origin === 'web'}
        <div class="rounded-xl border border-web/30 bg-web-soft/60 p-3">
          <p class="label !text-web">From the web · not from your library</p>
          <p class="mt-1 text-[0.9375rem] leading-relaxed text-ink">{segment.text}</p>
          <div class="mt-2 flex flex-wrap gap-1.5">
            {#each segment.citations as citation, j (j)}<CitationChip {citation} />{/each}
          </div>
        </div>
      {:else}
        <p class="text-[0.9375rem] leading-relaxed text-ink">
          {segment.text}
          {#each segment.citations as citation, j (j)}<span class="ml-1 inline-block"><CitationChip {citation} /></span>{/each}
        </p>
      {/if}
    {/each}
  </div>
  <p class="label mt-4 border-t border-line pt-3">
    {grounding ? GROUNDING_LABEL[grounding] : 'Answer'}{dropped > 0 ? ` · ${dropped} unverifiable sentence${dropped === 1 ? '' : 's'} removed` : ''}
  </p>
</div>
