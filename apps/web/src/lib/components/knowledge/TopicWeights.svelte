<script lang="ts">
  import { enhance } from '$app/forms';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import TopicWeightRow from '$lib/components/TopicWeightRow.svelte';
  import { WEIGHT_TARGETS, type TopicWeightOut, type WeightTarget } from '$lib/types/knowledge';

  let { weights, target }: { weights: TopicWeightOut[]; target: WeightTarget | null } = $props();
  let pending = $derived(weights.filter((w) => !w.approved).length);
  let confirming = $state(false);
  let form: HTMLFormElement | undefined = $state();
</script>

<div class="mb-3 flex flex-wrap items-end justify-between gap-3">
  <form method="GET" class="flex items-end gap-2">
    <label class="block">
      <span class="label">Exam</span>
      <select name="target" class="field mt-1.5" value={target ?? ''} onchange={(e) => e.currentTarget.form?.requestSubmit()}>
        <option value="">All</option>
        {#each WEIGHT_TARGETS as value (value)}<option {value}>{value}</option>{/each}
      </select>
    </label>
    <noscript><button class="btn btn-ghost" type="submit">Show</button></noscript>
  </form>
  {#if target && pending > 0}
    <form bind:this={form} method="POST" action="?/approve" use:enhance>
      <input type="hidden" name="exam_target" value={target} />
      <button type="button" class="btn btn-ghost" onclick={() => (confirming = true)}>Approve all {pending} for {target}</button>
    </form>
  {/if}
</div>

{#if weights.length === 0}
  <p class="text-sm text-muted">No weights computed yet. Extract a past paper below to derive them.</p>
{:else}
  <div class="panel overflow-x-auto">
    <table class="w-full min-w-[40rem] text-left text-sm">
      <thead class="label border-b border-line">
        <tr><th class="px-4 py-3 font-normal">Topic</th><th class="px-4 py-3 font-normal">Exam</th><th class="px-4 py-3 font-normal">Weight</th><th class="px-4 py-3 font-normal">Basis</th><th class="px-4 py-3 font-normal">Status</th></tr>
      </thead>
      <tbody class="divide-y divide-line">
        {#each weights as weight (weight.id)}<TopicWeightRow {weight} />{/each}
      </tbody>
    </table>
  </div>
{/if}

<ConfirmDialog bind:open={confirming} title="Approve all {target} weights?" confirmLabel="Approve all" onconfirm={() => form?.requestSubmit()}>
  <p>{pending} computed weights for {target} will start shaping your daily plan and question mix. Nothing changes without this approval.</p>
</ConfirmDialog>
