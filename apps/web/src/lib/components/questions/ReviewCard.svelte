<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationList from '$lib/components/CitationList.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import { optionLetter } from '$lib/questions';
  import type { ReviewItem } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';

  let { item, error = null }: { item: ReviewItem; error?: string | null } = $props();
  let busy = $state(false);
  let image = $derived(mediaUrl(item.figure_image_path));
  let sba = $derived(item.type === 'sba');
  const TYPE_LABEL: Record<string, string> = { sba: 'SBA', seq: 'SEQ', image_case: 'Image case', viva: 'Viva' };

  const submitting = () => {
    busy = true;
    return async ({ update }: { update: () => Promise<void> }) => {
      await update();
      busy = false;
    };
  };
</script>

<article class="panel p-5 sm:p-6" aria-labelledby="r-{item.id}">
  <p class="label">{TYPE_LABEL[item.type] ?? item.type}{item.topic ? ` · ${item.topic}` : ''}{item.exam_tags.length ? ` · ${item.exam_tags.join(', ')}` : ''}</p>
  <p id="r-{item.id}" class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{item.stem}</p>
  {#if image}<img src={image} alt="Figure for this draft" class="mt-3 max-h-72 w-auto rounded-xl bg-stage" />{/if}

  {#if item.checker_reasons.length}
    <ul class="mt-3 flex flex-col gap-1 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn" aria-label="Checker reasons">
      {#each item.checker_reasons as reason, i (i)}<li>{reason}</li>{/each}
    </ul>
  {/if}

  {#if sba}
    <ol class="mt-4 flex flex-col gap-2">
      {#each item.options as option, i (i)}
        <li class="rounded-xl border px-4 py-2.5 text-sm {i === item.key ? 'border-ok/40 bg-ok-soft' : 'border-line'}">
          <p class="text-ink"><span class="font-mono text-xs text-muted">{optionLetter(i)}</span> {option.text}{i === item.key ? ' (key)' : ''}</p>
          <p class="text-ink-2">{option.explanation}</p>
          <CitationList citations={option.citations} class="mt-1" />
        </li>
      {/each}
    </ol>
  {:else}
    <div class="mt-4 text-sm">
      <p class="label">Model answer</p>
      <p class="mt-1 whitespace-pre-line text-ink-2">{item.model_answer}</p>
      <ol class="mt-3 flex flex-col divide-y divide-line">
        {#each item.marking_scheme as point, i (i)}
          <li class="py-2"><span class="text-ink">{point.point}</span> <span class="font-mono text-xs text-muted">{point.marks} marks</span><CitationList citations={point.citations} class="mt-1" /></li>
        {/each}
      </ol>
    </div>
  {/if}
  {#if item.explanation}<p class="mt-3 text-sm leading-relaxed text-ink-2">{item.explanation}</p>{/if}
  <CitationList citations={item.citations} class="mt-3" />

  {#if error}<div class="mt-4"><Notice tone="warn">{error}</Notice></div>{/if}

  <div class="mt-4 flex flex-wrap gap-2">
    <form method="POST" action="?/review" use:enhance={submitting}>
      <input type="hidden" name="question_id" value={item.id} />
      <button class="btn btn-primary" name="action" value="approve" disabled={busy}>Approve</button>
      <button class="btn btn-ghost" name="action" value="reject" disabled={busy}>Reject</button>
    </form>
  </div>

  <details class="mt-4">
    <summary class="cursor-pointer text-sm text-ink-2">Edit wording (citations stay as generated)</summary>
    <form method="POST" action="?/review" class="mt-3 flex flex-col gap-3" use:enhance={submitting}>
      <input type="hidden" name="question_id" value={item.id} />
      <input type="hidden" name="action" value="edit" />
      <label class="block"><span class="label">Topic</span><input name="topic" value={item.topic} maxlength="300" class="field mt-1.5 w-full" /></label>
      <label class="block"><span class="label">Stem</span><textarea name="stem" class="field mt-1.5 min-h-24 w-full" maxlength="8000">{item.stem}</textarea></label>
      {#if sba}
        <fieldset class="flex flex-col gap-2">
          <legend class="label">Options (select the key)</legend>
          {#each item.options as option, i (i)}
            <div class="flex items-center gap-2">
              <input type="radio" name="key_index" value={i} checked={i === item.key} aria-label="Option {optionLetter(i)} is the key" />
              <input name="option_{i}" value={option.text} maxlength="8000" class="field w-full" aria-label="Option {optionLetter(i)}" />
            </div>
          {/each}
        </fieldset>
      {:else}
        <label class="block"><span class="label">Model answer</span><textarea name="model_answer" class="field mt-1.5 min-h-24 w-full" maxlength="8000">{item.model_answer}</textarea></label>
      {/if}
      <label class="block"><span class="label">Explanation</span><textarea name="explanation" class="field mt-1.5 min-h-20 w-full" maxlength="8000">{item.explanation}</textarea></label>
      <div><button class="btn btn-ghost" disabled={busy}>Save edits</button></div>
    </form>
  </details>
</article>
