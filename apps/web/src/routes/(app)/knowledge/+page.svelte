<script lang="ts">
  import ConflictCard from '$lib/components/knowledge/ConflictCard.svelte';
  import ExtractForm from '$lib/components/knowledge/ExtractForm.svelte';
  import TopicWeights from '$lib/components/knowledge/TopicWeights.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Knowledge · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Knowledge"
  title="What your sources say"
  description="Concepts and cited claims extracted from your library, places where sources disagree, and the topic weights that shape your plan."
/>

<p class="-mt-2 mb-6 text-sm">
  <a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/knowledge/review">Review low-confidence curriculum mappings →</a>
</p>

{#snippet feedback(section: string)}
  {#if form?.section === section}
    <div class="mb-3">
      {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok">{form.message}</Notice>{/if}
    </div>
  {/if}
{/snippet}

<div class="flex flex-col gap-10">
  <section aria-labelledby="concepts-heading">
    <h2 id="concepts-heading" class="mb-3 text-xl font-semibold text-ink">Concepts</h2>
    <form method="GET" class="mb-4 flex gap-2" role="search">
      {#if data.target}<input type="hidden" name="target" value={data.target} />{/if}
      <label for="concept-q" class="sr-only">Search concepts</label>
      <input id="concept-q" name="q" value={data.q ?? ''} maxlength="200" placeholder="e.g. pneumothorax" class="field max-w-md" />
      <button class="btn btn-ghost" type="submit">Search</button>
    </form>
    {#if data.conceptsProblem}
      <LoadIssue compact problem={data.conceptsProblem} title="Concepts are unreachable" icon="knowledge" />
    {:else if data.concepts.length === 0}
      <p class="text-sm text-muted">{data.q ? 'No concepts match.' : 'No concepts extracted yet. Extract a source below.'}</p>
    {:else}
      <ul class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each data.concepts as concept (concept.id)}
          <li>
            <a href="/knowledge/{concept.id}" class="block rounded-xl border border-line bg-surface px-4 py-3 hover:border-accent">
              <span class="block font-medium text-ink">{concept.name}</span>
              <span class="label mt-0.5 block">
                {concept.concept_type}{concept.curriculum_code ? ` · ${concept.curriculum_code}` : ''} · {concept.claim_count} claims{concept.open_conflicts ? ` · ${concept.open_conflicts} conflicts` : ''}
              </span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section aria-labelledby="conflicts-heading">
    <h2 id="conflicts-heading" class="mb-3 text-xl font-semibold text-ink">Open source conflicts</h2>
    {@render feedback('resolve')}
    {#if data.conflictsProblem}
      <LoadIssue compact problem={data.conflictsProblem} title="Conflicts are unreachable" icon="alert" />
    {:else if data.conflicts.length === 0}
      <p class="text-sm text-muted">No open conflicts between your sources.</p>
    {:else}
      <ul class="flex flex-col gap-4">
        {#each data.conflicts as conflict (conflict.id)}<ConflictCard {conflict} />{/each}
      </ul>
    {/if}
  </section>

  <section aria-labelledby="weights-heading">
    <h2 id="weights-heading" class="mb-1 text-xl font-semibold text-ink">Topic weights</h2>
    <p class="mb-3 text-sm text-ink-2">Computed from past papers. Nothing changes your plan until you approve it.</p>
    {@render feedback('weights')}
    {#if data.weightsProblem}
      <LoadIssue compact problem={data.weightsProblem} title="Topic weights are unreachable" icon="progress" />
    {:else}
      <TopicWeights weights={data.weights} target={data.target} />
    {/if}
  </section>

  <section aria-labelledby="extract-heading">
    <h2 id="extract-heading" class="mb-1 text-xl font-semibold text-ink">Extract knowledge from a source</h2>
    <p class="mb-3 text-sm text-ink-2">Notes yield concepts and cited claims; past papers also yield topic weights.</p>
    {@render feedback('extract')}
    <ExtractForm sources={data.sources} />
  </section>
</div>
