<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';

  let {
    sources,
    error = null,
    summary = null
  }: {
    sources: { id: string; title: string }[];
    error?: string | null;
    summary?: string | null;
  } = $props();
  let busy = $state(false);
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="generate-heading">
  <h2 id="generate-heading" class="text-xl font-semibold text-ink">Generate cards from a source</h2>
  <p class="mt-1 text-sm text-ink-2">Cards are written from passages that do not have cards yet, and each one cites its page.</p>
  {#if sources.length === 0}
    <p class="mt-4 text-sm text-muted">No processed sources yet. <a class="link" href="/library">Add one to the library.</a></p>
  {:else}
    <form
      method="POST"
      action="?/generate"
      class="mt-4 grid gap-3 sm:grid-cols-[1fr_7rem_auto] sm:items-end"
      use:enhance={() => {
        busy = true;
        return async ({ update }) => {
          await update();
          busy = false;
        };
      }}
    >
      <label class="block min-w-0">
        <span class="label">Source</span>
        <select name="source_id" required class="field mt-1.5">
          {#each sources as source (source.id)}<option value={source.id}>{source.title}</option>{/each}
        </select>
      </label>
      <label class="block">
        <span class="label">Cards</span>
        <input name="max_cards" type="number" min="1" max="20" value="8" required class="field mt-1.5 font-mono" />
      </label>
      <button class="btn btn-primary h-11" type="submit" disabled={busy}>{busy ? 'Writing cards…' : 'Generate'}</button>
    </form>
  {/if}
  {#if error}<div class="mt-3"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if summary}<div class="mt-3"><Notice tone="ok">{summary}</Notice></div>{/if}
</section>
