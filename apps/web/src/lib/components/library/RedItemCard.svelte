<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { formatDate } from '$lib/format';
  import { kindLabel, pagesLabel, reasonHint, reasonText } from '$lib/red-list';
  import type { RedItem } from '$lib/types/red-list';
  import FigureEvidence from './red/FigureEvidence.svelte';
  import NotesEvidence from './red/NotesEvidence.svelte';
  import PageEvidence from './red/PageEvidence.svelte';
  import VerdictChip from './red/VerdictChip.svelte';
  import VerdictForm from './red/VerdictForm.svelte';

  // One red-list entry with everything needed to judge it (ADR 0041).
  let { item, error = '', message = '' }: { item: RedItem; error?: string; message?: string } = $props();
  let pages = $derived(pagesLabel(item.page_from, item.page_to));
  let page = $derived(item.page_from ?? item.page_to);
  let reviewed = $derived(item.status === 'reviewed');
</script>

<li
  class="rounded-xl border border-l-4 p-4 [contain-intrinsic-size:auto_640px] [content-visibility:auto] sm:p-5 {reviewed
    ? 'border-line border-l-line-strong bg-surface-2'
    : 'border-danger/40 border-l-danger bg-danger-soft'}"
  aria-labelledby="item-{item.id}"
>
  <div class="flex min-w-0 items-start gap-3">
    <Icon name={reviewed ? 'check' : 'alert'} size={22} class="mt-0.5 hidden sm:block {reviewed ? 'text-muted' : 'text-danger'}" />
    <div class="min-w-0 flex-1">
      <h3 id="item-{item.id}" class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span class="rounded-md bg-danger px-1.5 py-0.5 font-mono text-[0.6875rem] font-semibold tracking-wide text-surface uppercase">
          {kindLabel(item.kind)}
        </span>
        <span class="min-w-0 font-display text-base font-semibold wrap-anywhere text-ink">{item.file_name}</span>
        <span class="text-sm font-semibold text-ink">· {pages || 'page unknown'}</span>
      </h3>
      <p class="mt-1.5 font-medium text-danger">{reasonText(item.reason)}</p>
      <p class="mt-1 text-sm text-ink"><span class="font-semibold">What to check:</span> {reasonHint(item.reason)}</p>
      <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        Flagged {formatDate(item.created_at)}
        {#if reviewed}<VerdictChip verdict={item.verdict} />{/if}
      </p>
      {#if reviewed && item.note}
        <p class="mt-2 text-sm break-words text-ink-2"><span class="font-semibold text-ink">Your note:</span> {item.note}</p>
      {/if}

      <div class="mt-4">
        {#if item.kind === 'page'}
          <PageEvidence {item} {page} />
        {:else if item.kind === 'figure'}
          <FigureEvidence {item} {page} />
        {:else}
          <NotesEvidence {item} {page} />
        {/if}
      </div>

      <VerdictForm id={item.id} verdict={item.verdict} note={item.note} {error} {message} />
    </div>
  </div>
</li>
