<script lang="ts">
  import { enhance } from '$app/forms';
  import { WEIGHT_TARGETS } from '$lib/types/knowledge';

  let { sources }: { sources: { id: string; title: string }[] } = $props();
  let mode = $state<'notes' | 'past_paper'>('notes');
</script>

{#if sources.length === 0}
  <p class="text-sm text-muted">No processed sources yet. <a class="link" href="/library">Add one to the library.</a></p>
{:else}
  <form method="POST" action="?/extract" use:enhance class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
    <label class="block lg:col-span-2">
      <span class="label">Source</span>
      <select name="source_id" required class="field mt-1.5">
        {#each sources as source (source.id)}<option value={source.id}>{source.title}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Kind</span>
      <select name="mode" bind:value={mode} class="field mt-1.5">
        <option value="notes">Notes / textbook</option>
        <option value="past_paper">Past paper</option>
      </select>
    </label>
    {#if mode === 'past_paper'}
      <label class="block">
        <span class="label">Exam</span>
        <select name="exam_target" required class="field mt-1.5">
          {#each WEIGHT_TARGETS.filter((t) => t !== 'all') as value (value)}<option {value}>{value}</option>{/each}
        </select>
      </label>
      <label class="block">
        <span class="label">Year</span>
        <input name="year" type="number" min="1990" max="2100" class="field mt-1.5 font-mono" />
      </label>
    {/if}
    <div><button class="btn btn-primary" type="submit">Extract</button></div>
  </form>
{/if}
