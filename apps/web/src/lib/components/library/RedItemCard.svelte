<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';
  import { formatDate } from '$lib/format';
  import { itemPage, kindLabel, pagesLabel, reasonText } from '$lib/red-list';
  import type { RedItem } from '$lib/types/red-list';

  let { item, error = '' }: { item: RedItem; error?: string } = $props();
  let busy = $state(false);
  let pages = $derived(pagesLabel(item.page_from, item.page_to));
</script>

<li class="rounded-xl border border-l-4 border-danger/40 border-l-danger bg-danger-soft p-4 sm:p-5 {busy ? 'opacity-60' : ''}">
  <div class="flex items-start gap-3">
    <Icon name="alert" size={22} class="mt-0.5 text-danger" />
    <div class="min-w-0 flex-1">
      <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span class="rounded-md bg-danger px-1.5 py-0.5 font-mono text-[0.6875rem] font-semibold tracking-wide text-surface uppercase">
          {kindLabel(item.kind)}
        </span>
        <span class="font-display text-base font-semibold break-words text-ink">{item.source_title}</span>
        {#if pages}<span class="text-sm text-ink-2">· {pages}</span>{/if}
      </p>
      <p class="mt-1.5 font-medium text-danger">{reasonText(item.reason)}</p>
      <p class="mt-1 text-xs text-muted">Flagged {formatDate(item.created_at)}</p>
      {#if error}<p class="mt-2 text-sm font-medium text-danger" role="alert">{error}</p>{/if}
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <a class="btn btn-ghost min-h-9 bg-surface px-3 py-1.5 text-sm" href={readerHref(item.source_id, itemPage(item.page_from, item.page_to))}>
          Open the page <Icon name="right" size={14} />
        </a>
        <form
          method="POST"
          action="?/reviewed"
          use:enhance={() => {
            busy = true;
            return async ({ update }) => {
              await update();
              busy = false;
            };
          }}
        >
          <input type="hidden" name="id" value={item.id} />
          <button class="btn btn-danger min-h-9 px-3 py-1.5 text-sm" disabled={busy}>
            <Icon name="check" size={14} /> Mark as reviewed
          </button>
        </form>
      </div>
    </div>
  </div>
</li>
