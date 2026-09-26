<script lang="ts">
  import { enhance } from '$app/forms';
  import { percent } from '$lib/format';
  import type { TopicWeight } from '$lib/types/knowledge';
  import CitationChip from './CitationChip.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';
  import StatusBadge from './StatusBadge.svelte';

  let { weight }: { weight: TopicWeight } = $props();
  let confirming = $state(false);
  let form: HTMLFormElement | undefined = $state();
</script>

<li class="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:gap-5">
  <div class="min-w-0 flex-1">
    <p class="flex flex-wrap items-center gap-2">
      <span class="font-mono text-xs text-muted">{weight.code}</span>
      <span class="font-medium text-ink">{weight.name}</span>
      <StatusBadge status={weight.status} />
    </p>
    {#if weight.rationale}<p class="mt-1 text-sm text-ink-2">{weight.rationale}</p>{/if}
    {#if weight.citations?.length}
      <div class="mt-1.5 flex flex-wrap gap-1.5">
        {#each weight.citations as citation, i (i)}<CitationChip {citation} />{/each}
      </div>
    {/if}
  </div>
  <p class="font-mono text-sm text-ink tabular-nums">
    <span class="text-muted">{percent(weight.current)}</span> → <strong>{percent(weight.proposed)}</strong>
  </p>
  {#if weight.status === 'proposed'}
    <form bind:this={form} method="POST" action="?/approve" use:enhance>
      <input type="hidden" name="weight_id" value={weight.id} />
      <button type="button" class="btn btn-ghost min-h-9 py-1.5" onclick={() => (confirming = true)}>Approve</button>
    </form>
  {/if}
</li>

<ConfirmDialog bind:open={confirming} title="Approve this weight?" confirmLabel="Approve" onconfirm={() => form?.requestSubmit()}>
  <p>
    <strong class="text-ink">{weight.name}</strong> will count for {percent(weight.proposed)} of your plan (was
    {percent(weight.current)}). Your daily plan and question mix will re-balance.
  </p>
</ConfirmDialog>
