<script lang="ts">
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import SourceRow from '$lib/components/library/SourceRow.svelte';
  import Uploader from '$lib/components/library/Uploader.svelte';
  import { isProcessing } from '$lib/pipeline';
  import { pollWhile } from '$lib/poll.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let processing = $derived(data.sources.filter((s) => isProcessing(s.status, s.steps)).length);
  let totalPages = $derived(data.sources.reduce((sum, s) => sum + (s.page_count ?? 0), 0));
  let totalFigures = $derived(data.sources.reduce((sum, s) => sum + s.figure_count, 0));

  pollWhile(() => processing > 0, 'app:library');
</script>

<svelte:head><title>Library · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Library"
  title="Your sources"
  description="Textbooks, notes, slides, and key images. Each page is rendered, indexed, and parsed so every answer can cite it back to the block."
/>

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
  <div class="order-2 min-w-0 lg:order-1">
    {#if form?.error}
      <div class="mb-4"><Notice tone="danger">{form.error}</Notice></div>
    {/if}
    {#if data.state === 'offline'}
      <ComingOnline
        title="Library service unreachable"
        description="The web app could not reach the library API. Uploaded files are safe; try again in a moment."
        endpoints={['/v1/library/sources']}
        icon="library"
      />
    {:else if data.state === 'error'}
      <Notice tone="danger">{data.detail}</Notice>
    {:else if data.sources.length === 0}
      <div class="panel px-6 py-12 text-center">
        <p class="font-display text-xl text-ink">Your shelf is empty.</p>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">
          Start with the book you revise from most. Native text is searchable within minutes; figures and layout follow.
        </p>
      </div>
    {:else}
      <div class="mb-3 flex items-center justify-between">
        <p class="label">{data.sources.length} sources</p>
        {#if processing}
          <p class="flex items-center gap-2 font-mono text-[0.6875rem] text-warn" role="status">
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-warn"></span>{processing} processing · live
          </p>
        {/if}
      </div>
      <ul class="flex flex-col gap-3">
        {#each data.sources as source (source.id)}
          <SourceRow {source} />
        {/each}
      </ul>
    {/if}
  </div>

  <aside class="order-1 flex flex-col gap-4 lg:order-2">
    <Uploader />
    <dl class="panel grid grid-cols-3 divide-x divide-line text-center">
      <div class="px-2 py-4"><dt class="label">Sources</dt><dd class="mt-1 font-display text-2xl text-ink">{data.sources.length}</dd></div>
      <div class="px-2 py-4"><dt class="label">Pages</dt><dd class="mt-1 font-display text-2xl text-ink">{totalPages}</dd></div>
      <div class="px-2 py-4"><dt class="label">Figures</dt><dd class="mt-1 font-display text-2xl text-ink">{totalFigures}</dd></div>
    </dl>
  </aside>
</div>
