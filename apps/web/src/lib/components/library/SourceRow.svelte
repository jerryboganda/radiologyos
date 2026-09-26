<script lang="ts">
  import { enhance } from '$app/forms';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatBytes, formatDate } from '$lib/format';
  import { isProcessing } from '$lib/pipeline';
  import type { SourceRow } from '$lib/types/library';
  import StepTrack from './StepTrack.svelte';

  let { source }: { source: SourceRow } = $props();
  let confirming = $state(false);
  let deleting = $state(false);
  let form: HTMLFormElement | undefined = $state();
  let active = $derived(isProcessing(source.status, source.steps));
  let pages = $derived(source.page_count ?? 0);
  let openable = $derived(pages > 0);
</script>

<li class="panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-5 {deleting ? 'opacity-50' : ''}">
  <div
    class="hidden h-12 w-10 shrink-0 items-center justify-center rounded-md border border-line bg-surface-2 font-mono text-[0.625rem] text-muted uppercase sm:flex"
    aria-hidden="true"
  >
    {source.kind}
  </div>
  <div class="min-w-0 flex-1">
    <div class="flex flex-wrap items-center gap-2">
      {#if openable}
        <a href="/library/{source.id}" class="truncate font-display text-lg font-semibold text-ink hover:text-accent">{source.title}</a>
      {:else}
        <span class="truncate font-display text-lg font-semibold text-ink">{source.title}</span>
      {/if}
      <StatusBadge status={source.status} />
    </div>
    <p class="mt-1 font-mono text-[0.6875rem] tracking-wide text-muted">
      {pages ? `${pages} PAGES` : 'PAGES PENDING'} · {source.figure_count} FIGURES · {formatBytes(source.byte_size)} · {formatDate(source.created_at)}
      {#if pages && source.pages_parsed < pages && source.status === 'ready'}
        · VISION {source.pages_parsed}/{pages}
      {/if}
    </p>
    {#if source.steps && (active || source.status === 'failed')}
      <div class="mt-3 max-w-xl"><StepTrack steps={source.steps} /></div>
    {/if}
  </div>
  <div class="flex items-center gap-2 self-end sm:self-center">
    {#if openable}
      <a href="/library/{source.id}" class="btn btn-ghost min-h-9 py-1.5">Read</a>
    {/if}
    <form
      bind:this={form}
      method="POST"
      action="?/delete"
      use:enhance={() => {
        deleting = true;
        return async ({ update }) => {
          await update();
          deleting = false;
        };
      }}
    >
      <input type="hidden" name="id" value={source.id} />
      <button
        type="button"
        class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"
        aria-label="Delete {source.title}"
        disabled={deleting}
        onclick={() => (confirming = true)}
      >
        <Icon name="trash" size={18} />
      </button>
    </form>
  </div>
</li>

<ConfirmDialog bind:open={confirming} title="Delete this source?" confirmLabel="Delete" danger onconfirm={() => form?.requestSubmit()}>
  <p>
    <strong class="text-ink">{source.title}</strong> and its pages, figures, and search index will be permanently removed.
    Citations pointing to it will stop resolving.
  </p>
</ConfirmDialog>
