<script lang="ts">
  import FigureActions from '$lib/components/FigureActions.svelte';
  import FigureHitCard from '$lib/components/FigureHitCard.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Similar figures · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Library"
  title="Similar figures"
  description="Figures from your own library that are closest in meaning to this one, ranked by their AI descriptions. Open one to see it on its page."
/>

<div class="mb-6 flex flex-wrap items-center gap-4">
  <img
    src="/media/figures/{data.figureId}"
    alt="The figure these are compared with"
    class="h-28 w-40 rounded-xl border border-line bg-stage object-contain"
  />
  <FigureActions figureId={data.figureId} />
</div>

{#if data.problem}
  <LoadIssue problem={data.problem} title="Similar figures are unavailable" icon="image" />
{:else if data.figures.length === 0}
  <p class="text-sm text-muted">No similar figures yet. Figures appear here once more pages have been vision-parsed and described.</p>
{:else}
  <ul class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
    {#each data.figures as figure (figure.figure_id)}<FigureHitCard {figure} />{/each}
  </ul>
{/if}
