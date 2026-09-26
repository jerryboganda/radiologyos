<script lang="ts">
  import MappingCard from '$lib/components/knowledge/MappingCard.svelte';
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
  description="Passages the classifier mapped to a curriculum system with low confidence. Accept, reject, or pick the right system; every decision is recorded."
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
  <p class="label mb-3">{data.mappings.length} awaiting review</p>
  <ul class="flex flex-col gap-3">
    {#each data.mappings as mapping (mapping.id)}<MappingCard {mapping} systems={data.systems} />{/each}
  </ul>
{/if}
