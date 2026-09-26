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

<section class="panel p-5 sm:p-6" aria-labelledby="knowledge-cards-heading">
  <h2 id="knowledge-cards-heading" class="text-xl font-semibold text-ink">Cards from your knowledge</h2>
  <p class="mt-1 text-sm text-ink-2">
    Cloze cards blank the key term of a verified claim; image cards show a described figure and ask for the finding. Each cites its page, and no model is called.
  </p>
  <form
    method="POST"
    action="?/knowledgeCards"
    class="mt-4 grid gap-3 sm:grid-cols-2"
    use:enhance={() => {
      busy = true;
      return async ({ update }) => {
        await update();
        busy = false;
      };
    }}
  >
    <fieldset class="sm:col-span-2">
      <legend class="label">Card type</legend>
      <div class="mt-1.5 flex flex-wrap gap-4 text-sm text-ink">
        <label class="flex items-center gap-2"><input type="radio" name="kind" value="cloze" checked /> Cloze (claims)</label>
        <label class="flex items-center gap-2"><input type="radio" name="kind" value="image" /> Image (figures)</label>
      </div>
    </fieldset>
    <label class="block min-w-0">
      <span class="label">Topic (optional)</span>
      <input name="topic" maxlength="200" placeholder="e.g. pneumothorax or CHEST" class="field mt-1.5" />
    </label>
    <label class="block min-w-0">
      <span class="label">Source (optional)</span>
      <select name="source_id" class="field mt-1.5">
        <option value="">All my sources</option>
        {#each sources as source (source.id)}<option value={source.id}>{source.title}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Cards</span>
      <input name="max_cards" type="number" min="1" max="50" value="20" required class="field mt-1.5 font-mono" />
    </label>
    <button class="btn btn-primary h-11 self-end" type="submit" disabled={busy}>{busy ? 'Making cards…' : 'Make cards'}</button>
  </form>
  {#if error}<div class="mt-3"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if summary}<div class="mt-3"><Notice tone="ok">{summary}</Notice></div>{/if}
</section>
