<script lang="ts">
  import type { RedItem } from '$lib/types/red-list';
  import PageThumb from './PageThumb.svelte';

  // The page's own text layer beside what the AI read for that page.
  let { item, page }: { item: RedItem; page: number | null } = $props();
</script>

<div class="grid gap-3 md:grid-cols-2">
  <section class="min-w-0 rounded-lg border border-line bg-surface p-3">
    <h4 class="label mb-2">Text on the page</h4>
    {#if item.own_text}
      <p class="max-h-80 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap break-words text-ink">{item.own_text}</p>
    {:else}
      <p class="text-sm text-muted italic">This page has no text layer (it may be a scan or an image).</p>
    {/if}
  </section>
  <section class="min-w-0 rounded-lg border border-line bg-surface p-3">
    <h4 class="label mb-2">What the AI read</h4>
    {#if item.reading}
      <p class="max-h-80 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap break-words text-ink">{item.reading}</p>
    {:else}
      <p class="text-sm font-medium text-danger">The AI read nothing from this page.</p>
    {/if}
  </section>
</div>
{#if page !== null}
  <div class="mt-3"><PageThumb sourceId={item.source_id} {page} fileName={item.file_name} /></div>
{/if}
