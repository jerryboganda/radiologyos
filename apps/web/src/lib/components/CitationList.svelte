<script lang="ts">
  import type { LooseCitation } from '$lib/types/citation';
  import CitationChip from './CitationChip.svelte';

  let { citations, class: extra = '' }: { citations: (LooseCitation | null | undefined)[] | null | undefined; class?: string } =
    $props();
</script>

{#if citations?.length}
  <div class="flex flex-wrap gap-1.5 {extra}">
    {#each citations as citation, i (i)}<CitationChip {citation} />{/each}
  </div>
{/if}
