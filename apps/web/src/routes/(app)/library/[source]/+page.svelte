<script lang="ts">
  import { page } from '$app/state';
  import { replaceState } from '$app/navigation';
  import Icon from '$lib/components/Icon.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import StepTrack from '$lib/components/library/StepTrack.svelte';
  import BlockList from '$lib/components/reader/BlockList.svelte';
  import FigurePanel from '$lib/components/reader/FigurePanel.svelte';
  import PageNav from '$lib/components/reader/PageNav.svelte';
  import PageViewer from '$lib/components/reader/PageViewer.svelte';
  import { readerHref } from '$lib/citations';
  import { isProcessing } from '$lib/pipeline';
  import { pollWhile } from '$lib/poll.svelte';
  import { mediaUrl, parseBlock } from '$lib/viewer';
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import TableList from '$lib/components/reader/TableList.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let selected = $state<number | null>(null);
  let showBlocks = $state(false);
  let tab = $state<'text' | 'figures' | 'tables'>('text');
  let copied = $state(false);
  let requeueing = $state(false);

  let source = $derived(data.source);
  let reader = $derived(data.page);
  let tables = $derived(reader?.tables ?? []);
  let pageCount = $derived(reader?.page_count ?? source.page_count ?? 0);
  let processing = $derived(isProcessing(source.status, source.steps));
  let imageUrl = $derived(mediaUrl(reader?.image_path));

  $effect(() => {
    selected = parseBlock(page.url.searchParams.get('block'));
  });

  pollWhile(() => processing, 'app:reader');

  function select(block: number) {
    selected = block;
    tab = 'text';
    replaceState(readerHref(source.id, data.pageNo, block), page.state);
  }

  async function copyLink() {
    const href = readerHref(source.id, data.pageNo, selected);
    try {
      await navigator.clipboard.writeText(new URL(href, location.origin).toString());
      copied = true;
      setTimeout(() => (copied = false), 1600);
    } catch {
      copied = false;
    }
  }
</script>

<svelte:head><title>{source.title} · p.{data.pageNo} · radbrain</title></svelte:head>

<div class="mb-5 flex flex-wrap items-end justify-between gap-4">
  <div class="min-w-0">
    <a href="/library" class="label inline-flex items-center gap-1 hover:text-ink"><Icon name="left" size={12} /> Library</a>
    <h1 class="mt-1 truncate text-2xl font-semibold text-ink sm:text-3xl">{source.title}</h1>
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <StatusBadge status={source.status} />
      {#if reader?.text_origin}<span class="label">text: {reader.text_origin}</span>{/if}
      {#if reader?.vision_status}<span class="label">vision: {reader.vision_status}</span>{/if}
    </div>
  </div>
  <div class="flex flex-wrap items-center gap-2">
    <a
      href="/tutor?source={encodeURIComponent(source.id)}&page={data.pageNo}"
      class="btn btn-ghost min-h-9 px-2.5 py-1.5 text-sm"
      title="Open the tutor with this page's text and figures retrieved first"
    >
      <Icon name="tutor" size={16} /> Ask about this page
    </a>
    <form
      method="POST"
      action="?/reprocess"
      use:enhance={() => {
        requeueing = true;
        return async ({ update }) => {
          await update({ reset: false });
          requeueing = false;
        };
      }}
    >
      <button
        type="submit"
        class="btn btn-ghost min-h-9 px-2.5 py-1.5 text-sm"
        disabled={requeueing || processing}
        title="Re-run this source's pipeline: failed pages are read again; finished work and unchanged text are not paid for twice"
      >
        {requeueing ? 'Queuing…' : 'Re-process'}
      </button>
    </form>
    <PageNav sourceId={source.id} pageNo={data.pageNo} {pageCount} />
  </div>
</div>

{#if form}
  <div class="mb-5">
    {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
        >{form.message}</Notice
      >{/if}
  </div>
{/if}

{#if processing && source.steps.length}
  <div class="panel mb-5 p-4"><StepTrack steps={source.steps} /></div>
{/if}

<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
  <div class="min-w-0">
    {#if reader && imageUrl}
      <PageViewer
        src={imageUrl}
        alt="Page {data.pageNo} of {source.title}"
        corner="P. {data.pageNo}{pageCount ? ` / ${pageCount}` : ''}"
        blocks={reader.blocks}
        figures={reader.figures}
        {selected}
        bind:showBlocks
        onselect={select}
      />
    {:else}
      <div class="flex h-[50dvh] flex-col items-center justify-center rounded-2xl border border-stage-line bg-stage px-6 text-center">
        <p class="font-mono text-xs tracking-widest text-overlay uppercase">P. {data.pageNo}</p>
        <p class="mt-2 max-w-sm text-sm text-neutral-300">
          {processing ? 'This page is still being rendered. It will appear automatically.' : 'This page is not available.'}
        </p>
      </div>
    {/if}
  </div>

  <aside class="panel flex min-h-0 flex-col xl:sticky xl:top-6 xl:max-h-[calc(100dvh-3rem)]">
    <div class="flex items-center gap-1 border-b border-line p-2" role="tablist" aria-label="Page details">
      {#each [['text', `Text · ${reader?.blocks.length ?? 0}`], ['figures', `Figures · ${reader?.figures.length ?? 0}`], ['tables', `Tables · ${tables.length}`]] as [id, label] (id)}
        <button
          type="button"
          role="tab"
          aria-selected={tab === id}
          class="rounded-lg px-3 py-1.5 text-sm font-medium {tab === id ? 'bg-surface-2 text-ink' : 'text-muted hover:text-ink'}"
          onclick={() => (tab = id as 'text' | 'figures' | 'tables')}>{label}</button
        >
      {/each}
      <button type="button" class="ml-auto rounded-lg px-2.5 py-1.5 text-xs text-muted hover:text-accent" onclick={copyLink}>
        {copied ? 'Link copied' : selected != null ? `Copy link to #${selected}` : 'Copy page link'}
      </button>
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto p-2" role="tabpanel">
      {#if !reader}
        <p class="px-1 py-6 text-center text-sm text-muted">Nothing to show yet.</p>
      {:else if tab === 'text'}
        <BlockList blocks={reader.blocks} {selected} onselect={select} />
      {:else if tab === 'tables'}
        <TableList {tables} {selected} onselect={select} />
      {:else}
        <FigurePanel figures={reader.figures} visionStatus={reader.vision_status} />
      {/if}
    </div>
  </aside>
</div>
