<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';
  import type { RedItem } from '$lib/types/red-list';
  import Highlighted from './Highlighted.svelte';

  // A note section with every extracted statement's evidence highlighted, then
  // the statements themselves.
  let { item, page }: { item: RedItem; page: number | null } = $props();
  let spans = $derived(item.statements.map((s) => s.evidence_span));
</script>

<section class="min-w-0 rounded-lg border border-line bg-surface p-3">
  <h4 class="label mb-2">{item.section_heading || 'Section text'}</h4>
  {#if item.section_text}
    <div class="max-h-96 overflow-y-auto text-sm leading-relaxed text-ink">
      <Highlighted text={item.section_text} {spans} />
    </div>
  {:else}
    <p class="text-sm text-muted italic">This section no longer exists (the page was re-read).</p>
  {/if}
</section>
{#if item.statements.length}
  <h4 class="label mt-3 mb-2">Statements the AI took from it ({item.statements.length})</h4>
  <ol class="flex list-decimal flex-col gap-2 pl-5 text-sm">
    {#each item.statements as s, i (i)}
      <li class="break-words">
        <span class="text-ink">{s.statement}</span>
        {#if s.status === 'flagged'}
          <span class="ml-1 rounded bg-danger px-1 py-0.5 font-mono text-[0.625rem] font-semibold text-surface uppercase">flagged</span>
        {/if}
        <span class="block text-ink-2 italic">“{s.evidence_span}”</span>
      </li>
    {/each}
  </ol>
{/if}
{#if page !== null}
  <p class="mt-3 text-sm">
    <a class="link inline-flex items-center gap-1" href={readerHref(item.source_id, page)}>Open in reader <Icon name="right" size={14} /></a>
  </p>
{/if}
