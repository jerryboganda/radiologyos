<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import { QUESTION_TYPES } from '$lib/types/assessment';
  import { EXAM_TARGETS } from '$lib/types/study';

  let {
    sources,
    error = null,
    summary = null
  }: { sources: { id: string; title: string }[]; error?: string | null; summary?: string | null } = $props();
  let busy = $state(false);
  const TYPES = QUESTION_TYPES.filter((t) => t.value !== 'rapid_recall');
</script>

<details class="panel group p-5 sm:p-6" open={!!error || !!summary}>
  <summary class="cursor-pointer list-none text-lg font-semibold text-ink">
    Generate questions <span class="label ml-2 group-open:hidden">from a topic or your sources</span>
  </summary>
  <form
    method="POST"
    action="?/generate"
    class="mt-4 grid gap-4 sm:grid-cols-2"
    use:enhance={() => {
      busy = true;
      return async ({ update }) => {
        await update();
        busy = false;
      };
    }}
  >
    <label class="block">
      <span class="label">Type</span>
      <select name="type" class="field mt-1.5">
        {#each TYPES as type (type.value)}<option value={type.value}>{type.label}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Exam</span>
      <select name="exam_target" class="field mt-1.5">
        {#each EXAM_TARGETS as target (target.value)}<option value={target.value}>{target.label}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Topic (optional if sources chosen)</span>
      <input name="topic" maxlength="200" placeholder="e.g. Bosniak classification" class="field mt-1.5" />
    </label>
    <label class="block">
      <span class="label">How many (max 5)</span>
      <input name="count" type="number" min="1" max="5" value="3" required class="field mt-1.5 font-mono" />
    </label>
    {#if sources.length}
      <label class="block sm:col-span-2">
        <span class="label">Sources (optional; Ctrl/⌘-click for several)</span>
        <select name="source_ids" multiple size={Math.min(5, sources.length)} class="field mt-1.5">
          {#each sources as source (source.id)}<option value={source.id}>{source.title}</option>{/each}
        </select>
      </label>
    {/if}
    <div class="sm:col-span-2">
      <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Writing and checking questions…' : 'Generate'}</button>
    </div>
  </form>
  {#if error}<div class="mt-3"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if summary}<div class="mt-3"><Notice tone="ok">{summary}</Notice></div>{/if}
</details>
