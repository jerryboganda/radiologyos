<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { countsLabel, openCount, reasonText, topReasons } from '$lib/red-list';
  import type { FileSummary } from '$lib/types/red-list';

  // One file on the red review overview: what is open, why, and a link in.
  let { file }: { file: FileSummary } = $props();
  let open = $derived(openCount(file));
  let href = $derived(`/library/review/${encodeURIComponent(file.source_id)}`);
</script>

{#if open > 0}
  <li class="rounded-xl border border-l-4 border-danger/40 border-l-danger bg-danger-soft p-4 [contain-intrinsic-size:auto_220px] [content-visibility:auto] sm:p-5">
    <h3 class="font-display text-lg font-bold wrap-anywhere text-ink">{file.file_name}</h3>
    {#if file.source_title && file.source_title !== file.file_name}
      <p class="text-sm break-words text-ink-2">{file.source_title}</p>
    {/if}
    <p class="mt-2 font-semibold text-danger">{countsLabel(file)}</p>
    {#if Object.keys(file.reasons).length}
      <ul class="mt-2 flex flex-col gap-0.5 text-sm text-ink">
        {#each topReasons(file.reasons) as [code, n] (code)}
          <li class="break-words"><span class="font-mono font-semibold text-danger">{n}×</span> {reasonText(code)}</li>
        {/each}
      </ul>
    {/if}
    <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
      <span class="text-xs text-muted">{file.reviewed} reviewed</span>
      <a class="btn btn-danger min-h-10 px-4 text-sm" {href}>Review this file <Icon name="right" size={14} /></a>
    </div>
  </li>
{:else}
  <li class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ok/30 bg-ok-soft px-3 py-2 text-sm">
    <span class="flex min-w-0 items-center gap-2 text-ok">
      <Icon name="check" size={16} /><span class="font-semibold wrap-anywhere">{file.file_name}</span>
    </span>
    <a class="link text-sm" {href}>{file.reviewed} reviewed</a>
  </li>
{/if}
