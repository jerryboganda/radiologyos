<script lang="ts">
  import { citationHref } from '$lib/citations';
  import { highlight, snippet } from '$lib/format';
  import type { SearchHit } from '$lib/types/library';
  import CitationChip from './CitationChip.svelte';

  let { hit, query }: { hit: SearchHit; query: string } = $props();
  let parts = $derived(highlight(snippet(hit.text, query), query));
</script>

<li class="panel group p-4 sm:p-5">
  <a href={citationHref(hit.citation)} class="block">
    {#if hit.heading}
      <h3 class="font-display text-lg font-semibold text-ink group-hover:text-accent">{hit.heading}</h3>
    {/if}
    <p class="mt-1.5 text-[0.9375rem] leading-relaxed text-ink-2">
      {#each parts as part, i (i)}{#if part.match}<mark class="rounded-sm bg-accent-soft px-0.5 text-ink">{part.text}</mark
          >{:else}{part.text}{/if}{/each}
    </p>
  </a>
  <div class="mt-3 flex items-center justify-between gap-3">
    <CitationChip citation={hit.citation} />
    <span class="font-mono text-[0.625rem] text-muted" title="Fused relevance score">{hit.score.toFixed(3)}</span>
  </div>
</li>
