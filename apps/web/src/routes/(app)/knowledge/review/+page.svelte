<script lang="ts">
  import MappingCard from '$lib/components/knowledge/MappingCard.svelte';
  import MergeCard from '$lib/components/knowledge/MergeCard.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Curriculum review · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Knowledge"
  title="Curriculum review"
  description="Passages the classifier mapped to a curriculum system with low confidence. Accept, reject, or pick the right system, topic, or subtopic; every decision is recorded."
/>

<p class="mb-4 text-sm"><a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/knowledge">← Back to knowledge</a></p>

{#if form}
  <div class="mb-4">
    {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
        >{form.message}</Notice
      >{/if}
  </div>
{/if}

{#if data.mappingsProblem}
  <LoadIssue problem={data.mappingsProblem} title="The review queue is unreachable" icon="knowledge" />
{:else if data.mappings.length === 0}
  <Notice tone="ok">Nothing to review. Every curriculum mapping is decided.</Notice>
{:else}
  <datalist id="curriculum-nodes">
    {#each data.nodes as node (node.id)}<option value={node.id}>{node.path}</option>{/each}
  </datalist>
  <p class="label mb-3">{data.mappings.length} awaiting review</p>
  <ul class="flex flex-col gap-3">
    {#each data.mappings as mapping (mapping.id)}<MappingCard {mapping} systems={data.systems} />{/each}
  </ul>
{/if}

<section aria-labelledby="merges-heading" class="mt-10">
  <h2 id="merges-heading" class="mb-1 text-xl font-semibold text-ink">Possible duplicate concepts</h2>
  <p class="mb-3 text-sm text-ink-2">
    Similarly named concepts the resolver was not sure about. Merging moves the claims, links, and names to one concept, and can
    be undone.
  </p>
  {#if data.mergesProblem}
    <LoadIssue compact problem={data.mergesProblem} title="Duplicate review is unreachable" icon="knowledge" />
  {:else if data.merges.length === 0}
    <p class="text-sm text-muted">No pairs are waiting for you.</p>
  {:else}
    <ul class="flex flex-col gap-3">
      {#each data.merges as merge (merge.id)}<MergeCard {merge} />{/each}
    </ul>
  {/if}
  {#if data.applied.length}
    <details class="mt-4">
      <summary class="cursor-pointer text-sm text-accent">Recent merges ({data.applied.length})</summary>
      <ul class="mt-3 flex flex-col gap-3">
        {#each data.applied as merge (merge.id)}<MergeCard {merge} />{/each}
      </ul>
    </details>
  {/if}
</section>
