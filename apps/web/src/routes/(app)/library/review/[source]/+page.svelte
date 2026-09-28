<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import FlaggedFactCard from '$lib/components/library/FlaggedFactCard.svelte';
  import RedItemCard from '$lib/components/library/RedItemCard.svelte';
  import DangerHeader from '$lib/components/library/red/DangerHeader.svelte';
  import { openCount } from '$lib/red-list';
  import type { ActionData, PageData } from './$types';

  // One file's red-list entries with their evidence and the owner's verdicts
  // (ADR 0038, ADR 0041).
  let { data, form }: { data: PageData; form: ActionData } = $props();
  let dismissed = $state<ActionData | null>(null);

  let fileName = $derived(data.file?.file_name ?? data.items[0]?.file_name ?? data.facts[0]?.file_name ?? 'This file');
  let title = $derived(data.file?.source_title ?? data.items[0]?.source_title ?? data.facts[0]?.source_title ?? '');
  let isOpen = $derived(data.status === 'open');
  let here = $derived(data.items.length + data.facts.length);
  let openN = $derived(data.file ? openCount(data.file) : isOpen ? here : 0);
  let reviewedN = $derived(data.file ? data.file.reviewed : isOpen ? 0 : here);
  let toast = $derived(form && 'message' in form && form !== dismissed ? form.message : '');
  let pageError = $derived(form && 'error' in form && !form.id ? form.error : '');

  function feedback(section: 'items' | 'facts', id: string): { error: string; message: string } {
    if (!form || form.section !== section || form.id !== id) return { error: '', message: '' };
    return {
      error: 'error' in form ? (form.error ?? '') : '',
      message: 'message' in form ? (form.message ?? '') : ''
    };
  }

  const TAB = 'inline-flex min-h-10 items-center rounded-lg border px-3 text-sm font-semibold';
</script>

<svelte:head><title>{openN ? `(${openN}) ` : ''}{fileName} · Needs your review · radbrain</title></svelte:head>

<p class="mb-4 text-sm">
  <a href="/library/review" class="label inline-flex items-center gap-1 hover:text-ink"><Icon name="left" size={12} /> All files to review</a>
</p>

<DangerHeader title={fileName} eyebrow="Needs your review · check before you trust">
  {#if title && title !== fileName}<p class="font-medium break-words">{title}</p>{/if}
  <p>Judge each entry against the evidence shown, give your verdict, and add a note if something needs fixing.</p>
</DangerHeader>

<nav aria-label="Review status" class="mb-6 flex flex-wrap gap-2">
  <a href="?status=open" aria-current={isOpen ? 'page' : undefined} class="{TAB} {isOpen ? 'border-danger bg-danger text-surface' : 'border-line-strong bg-surface text-ink hover:bg-surface-2'}">
    To review ({openN})
  </a>
  <a href="?status=reviewed" aria-current={!isOpen ? 'page' : undefined} class="{TAB} {!isOpen ? 'border-ink bg-ink text-surface' : 'border-line-strong bg-surface text-ink hover:bg-surface-2'}">
    Reviewed ({reviewedN})
  </a>
</nav>

{#if pageError}<div class="mb-4"><Notice tone="danger">{pageError}</Notice></div>{/if}

{#if data.problem}
  <LoadIssue problem={data.problem} title="This file's review list is unreachable" icon="library" />
{:else}
  <section aria-labelledby="entries" class="mb-10">
    <h2 id="entries" class="mb-3 flex items-center gap-2 text-xl font-semibold text-ink">
      {isOpen ? 'Below the quality bar' : 'Your verdicts'}
      <span class="rounded-full px-2 py-0.5 font-mono text-xs {data.items.length && isOpen ? 'bg-danger text-surface' : 'bg-surface-2 text-muted'}">{data.items.length}</span>
    </h2>
    {#if data.items.length === 0}
      <p class="flex items-center gap-2 text-sm text-ok">
        <Icon name="check" size={16} />
        {isOpen ? 'Nothing in this file needs review.' : 'You have not judged anything in this file yet.'}
      </p>
    {:else}
      <ul class="flex flex-col gap-4">
        {#each data.items as item (item.id)}<RedItemCard {item} {...feedback('items', item.id)} />{/each}
      </ul>
    {/if}
  </section>

  {#if data.facts.length || isOpen}
    <section aria-labelledby="flagged-facts">
      <h2 id="flagged-facts" class="mb-1 flex items-center gap-2 text-xl font-semibold text-ink">
        Facts that may contradict standard teaching
        <span class="rounded-full px-2 py-0.5 font-mono text-xs {data.facts.length && isOpen ? 'bg-warn text-surface' : 'bg-surface-2 text-muted'}">{data.facts.length}</span>
      </h2>
      <p class="mb-3 text-sm text-ink-2">Keep each fact as your source states it, or reject it. You can change your mind later.</p>
      {#if data.facts.length === 0}
        <p class="flex items-center gap-2 text-sm text-ok"><Icon name="check" size={16} /> No flagged facts in this file.</p>
      {:else}
        <ul class="flex flex-col gap-4">
          {#each data.facts as fact (fact.id)}<FlaggedFactCard {fact} {...feedback('facts', fact.id)} />{/each}
        </ul>
      {/if}
    </section>
  {/if}
{/if}

{#if toast}
  <div class="fixed inset-x-4 bottom-4 z-30 mx-auto max-w-md shadow-lg">
    <Notice tone="ok">
      <span class="flex flex-wrap items-center gap-3">
        <span>{toast}{isOpen ? ' It has moved to Reviewed.' : ''}</span>
        <button type="button" class="link text-sm" onclick={() => (dismissed = form)}>Dismiss</button>
      </span>
    </Notice>
  </div>
{/if}
