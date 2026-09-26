<script lang="ts">
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import FigureHitCard from '$lib/components/FigureHitCard.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import SearchHitCard from '$lib/components/SearchHitCard.svelte';
  import { navigating } from '$app/state';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
  let busy = $derived(navigating.to?.url.pathname === '/search');
</script>

<svelte:head><title>{data.query ? `${data.query} · ` : ''}Search · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Search"
  title="Find it in your sources"
  description="Hybrid keyword and semantic search over your library. Every result is a cited passage — nothing here is generated."
/>

<form method="GET" class="mb-8 flex gap-2" role="search" data-sveltekit-keepfocus>
  <label for="q" class="sr-only">Search your library</label>
  <div class="relative flex-1">
    <Icon name="search" size={18} class="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-muted" />
    <input
      id="q"
      name="q"
      type="search"
      value={data.query}
      minlength="2"
      maxlength="500"
      required
      placeholder="e.g. deep sulcus sign, Bosniak IIF, scimitar"
      class="field h-12 pl-10 text-base"
      autocomplete="off"
    />
  </div>
  <button class="btn btn-primary h-12 px-5" type="submit" disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
</form>

{#if data.state === 'offline'}
  <ComingOnline title="Search is unreachable" description="The library API did not answer. Try again in a moment." endpoints={['/v1/library/search']} icon="search" />
{:else if data.state === 'error'}
  <Notice tone="danger">{data.detail}</Notice>
{:else if data.result}
  {@const result = data.result}
  <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
    <p class="label">{result.hits.length} passages · {result.figures.length} figures</p>
    <p class="label">{result.dense ? 'keyword + semantic' : 'keyword only (embeddings off)'}</p>
  </div>
  {#if result.hits.length === 0 && result.figures.length === 0}
    <div class="panel px-6 py-12 text-center">
      <p class="font-display text-xl text-ink">No cited passages for “{data.query}”.</p>
      <p class="mt-2 text-sm text-muted">Try a synonym, a shorter phrase, or upload the source that covers it.</p>
    </div>
  {/if}
  {#if result.figures.length}
    <section class="mb-8" aria-labelledby="fig-heading">
      <h2 id="fig-heading" class="mb-3 text-xl font-semibold text-ink">Figures</h2>
      <ul class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {#each result.figures as figure (figure.figure_id)}<FigureHitCard {figure} />{/each}
      </ul>
    </section>
  {/if}
  {#if result.hits.length}
    <section aria-labelledby="hits-heading">
      <h2 id="hits-heading" class="mb-3 text-xl font-semibold text-ink">Passages</h2>
      <ol class="flex flex-col gap-3">
        {#each result.hits as hit (hit.chunk_id)}<SearchHitCard {hit} query={data.query} />{/each}
      </ol>
    </section>
  {/if}
{:else}
  <div class="grid gap-3 sm:grid-cols-3">
    {#each ['Search by sign or eponym', 'Search by modality + anatomy', 'Open any result at the exact block'] as tip (tip)}
      <p class="rounded-xl border border-dashed border-line-strong px-4 py-5 text-sm text-muted">{tip}</p>
    {/each}
  </div>
{/if}
