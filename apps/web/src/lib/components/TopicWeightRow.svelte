<script lang="ts">
  import { enhance } from '$app/forms';
  import { percentFine as percent } from '$lib/format';
  import { basisText } from '$lib/knowledge';
  import type { TopicWeightOut } from '$lib/types/knowledge';
  import ConfirmDialog from './ConfirmDialog.svelte';
  import StatusBadge from './StatusBadge.svelte';

  let { weight }: { weight: TopicWeightOut } = $props();
  let confirming = $state(false);
  let form: HTMLFormElement | undefined = $state();
  let name = $derived(weight.topic || weight.curriculum_code);
</script>

<tr>
  <td class="px-4 py-3">
    <span class="font-mono text-xs text-muted">{weight.curriculum_code}</span>
    <span class="text-ink">{weight.topic || 'All topics in this system'}</span>
  </td>
  <td class="px-4 py-3 font-mono text-xs text-muted">{weight.exam_target}</td>
  <td class="px-4 py-3 font-mono text-sm text-ink tabular-nums">{percent(weight.weight)}</td>
  <td class="px-4 py-3 text-xs text-ink-2">{basisText(weight.basis)}</td>
  <td class="px-4 py-3">
    {#if weight.approved}
      <StatusBadge status="approved" />
    {:else}
      <form bind:this={form} method="POST" action="?/approve" use:enhance>
        <input type="hidden" name="weight_id" value={weight.id} />
        <input type="hidden" name="exam_target" value={weight.exam_target} />
        <button type="button" class="btn btn-ghost min-h-9 py-1.5" onclick={() => (confirming = true)}>Approve</button>
      </form>
      <ConfirmDialog bind:open={confirming} title="Approve this weight?" confirmLabel="Approve" onconfirm={() => form?.requestSubmit()}>
        <p>
          <strong class="text-ink">{name}</strong> will count for {percent(weight.weight)} of your {weight.exam_target} plan. Your daily
          plan and question mix will re-balance around approved weights.
        </p>
      </ConfirmDialog>
    {/if}
  </td>
</tr>
