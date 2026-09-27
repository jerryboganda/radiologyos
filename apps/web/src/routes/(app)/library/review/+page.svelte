<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import FlaggedFactCard from '$lib/components/library/FlaggedFactCard.svelte';
  import RedItemCard from '$lib/components/library/RedItemCard.svelte';
  import { redCount } from '$lib/red-list';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let items = $derived(data.list.items);
  let facts = $derived(data.list.flagged_facts);
  let total = $derived(redCount(data.list));

  function errorFor(section: 'items' | 'facts', id: string): string {
    if (!form || !('error' in form) || form.section !== section || form.id !== id) return '';
    return form.error;
  }
</script>

<svelte:head><title>{total ? `(${total}) ` : ''}Needs your review · radbrain</title></svelte:head>

<p class="mb-4 text-sm">
  <a href="/library" class="label inline-flex items-center gap-1 hover:text-ink"><Icon name="left" size={12} /> Library</a>
</p>

<header class="mb-8 flex items-start gap-4 rounded-xl border border-l-4 border-danger/40 border-l-danger bg-danger-soft p-4 sm:p-5">
  <svg viewBox="0 0 24 24" class="h-10 w-10 shrink-0 text-danger sm:h-12 sm:w-12" aria-hidden="true">
    <path fill="currentColor" d="M10.3 3.9a2 2 0 0 1 3.4 0l8.5 14.1a2 2 0 0 1-1.7 3H3.5a2 2 0 0 1-1.7-3z" />
    <path stroke="var(--danger-soft)" stroke-width="2.2" stroke-linecap="round" d="M12 9v4.5M12 17.2h.01" />
  </svg>
  <div class="min-w-0">
    <p class="label text-danger">Danger · check before you trust</p>
    <h1 class="mt-1 text-3xl leading-tight font-semibold text-danger sm:text-4xl">Needs your review</h1>
    <p class="mt-2 max-w-2xl text-[0.9375rem] leading-relaxed text-ink">
      These parts of your library fell short of the quality check, or no model could read them. Check each one against the original page.
    </p>
  </div>
</header>

{#if form && 'message' in form && form.message}
  <div class="mb-4"><Notice tone="ok">{form.message}</Notice></div>
{:else if form && 'error' in form && form.error && !form.id}
  <div class="mb-4"><Notice tone="danger">{form.error}</Notice></div>
{/if}

{#if data.problem}
  <LoadIssue problem={data.problem} title="The review list is unreachable" icon="library" />
{:else}
  <section aria-labelledby="below-bar" class="mb-10">
    <h2 id="below-bar" class="mb-3 flex items-center gap-2 text-xl font-semibold text-ink">
      Below the quality bar
      <span class="rounded-full px-2 py-0.5 font-mono text-xs {items.length ? 'bg-danger text-surface' : 'bg-surface-2 text-muted'}">{items.length}</span>
    </h2>
    {#if items.length === 0}
      <p class="flex items-center gap-2 text-sm text-ok"><Icon name="check" size={16} /> Nothing needs review right now.</p>
    {:else}
      <ul class="flex flex-col gap-3">
        {#each items as item (item.id)}<RedItemCard {item} error={errorFor('items', item.id)} />{/each}
      </ul>
    {/if}
  </section>

  <section aria-labelledby="flagged-facts">
    <h2 id="flagged-facts" class="mb-1 flex items-center gap-2 text-xl font-semibold text-ink">
      Facts that may contradict standard teaching
      <span class="rounded-full px-2 py-0.5 font-mono text-xs {facts.length ? 'bg-warn text-surface' : 'bg-surface-2 text-muted'}">{facts.length}</span>
    </h2>
    <p class="mb-3 text-sm text-ink-2">Keep each fact as your source states it, or reject it.</p>
    {#if facts.length === 0}
      <p class="flex items-center gap-2 text-sm text-ok"><Icon name="check" size={16} /> Nothing needs review right now.</p>
    {:else}
      <ul class="flex flex-col gap-3">
        {#each facts as fact (fact.id)}<FlaggedFactCard {fact} error={errorFor('facts', fact.id)} />{/each}
      </ul>
    {/if}
  </section>
{/if}
