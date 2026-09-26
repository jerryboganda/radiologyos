<script lang="ts">
  import CitationChip from '$lib/components/CitationChip.svelte';
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import TopicWeightRow from '$lib/components/TopicWeightRow.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Knowledge · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Knowledge"
  title="What your sources say"
  description="Concepts extracted from your library, places where sources disagree, and the topic weights that shape your plan."
/>

{#if form?.error}<div class="mb-5"><Notice tone="warn">{form.error}</Notice></div>{/if}

<div class="flex flex-col gap-8">
  <section aria-labelledby="weights-heading">
    <h2 id="weights-heading" class="mb-3 text-xl font-semibold text-ink">Topic weights</h2>
    {#if data.weights === null}
      <ComingOnline compact title="Topic weights coming online" description="Proposed curriculum weights will wait here for your approval — nothing changes your plan without it." endpoints={['/v1/knowledge/topic-weights']} icon="progress" />
    {:else if data.weights.length === 0}
      <p class="text-sm text-muted">No weights proposed.</p>
    {:else}
      <ul class="panel divide-y divide-line px-5">
        {#each data.weights as weight (weight.id)}<TopicWeightRow {weight} />{/each}
      </ul>
    {/if}
  </section>

  <section aria-labelledby="conflicts-heading">
    <h2 id="conflicts-heading" class="mb-3 text-xl font-semibold text-ink">Source conflicts</h2>
    {#if data.conflicts === null}
      <ComingOnline compact title="Conflict detection coming online" description="When two sources disagree (e.g. a size threshold), both claims appear side by side with citations." endpoints={['/v1/knowledge/conflicts']} icon="alert" />
    {:else if data.conflicts.length === 0}
      <p class="text-sm text-muted">No conflicts found between your sources.</p>
    {:else}
      <ul class="flex flex-col gap-4">
        {#each data.conflicts as conflict (conflict.id)}
          <li class="panel p-5">
            <p class="label">{conflict.concept} · {conflict.status}</p>
            <p class="mt-1 font-medium text-ink">{conflict.summary}</p>
            <div class="mt-3 grid gap-3 sm:grid-cols-2">
              {#each conflict.claims as claim, i (i)}
                <blockquote class="rounded-xl border-l-2 border-warn bg-surface-2/60 p-3 text-sm text-ink-2">
                  <p>{claim.text}</p>
                  <div class="mt-2"><CitationChip citation={claim.citation} /></div>
                </blockquote>
              {/each}
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section aria-labelledby="concepts-heading">
    <h2 id="concepts-heading" class="mb-3 text-xl font-semibold text-ink">Concepts</h2>
    {#if data.concepts === null}
      <ComingOnline compact title="Concept map coming online" description="Concepts and claims extracted from your sources will be browsable here." endpoints={['/v1/knowledge/concepts']} icon="knowledge" />
    {:else if data.concepts.length === 0}
      <p class="text-sm text-muted">No concepts extracted yet.</p>
    {:else}
      <ul class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each data.concepts as concept (concept.id)}
          <li class="rounded-xl border border-line bg-surface px-4 py-3">
            <p class="font-medium text-ink">{concept.name}</p>
            <p class="label mt-0.5">{concept.topic ?? 'general'} · {concept.claim_count} claims · {concept.source_count} sources</p>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>
