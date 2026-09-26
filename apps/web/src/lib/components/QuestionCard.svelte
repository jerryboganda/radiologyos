<script lang="ts">
  import { enhance } from '$app/forms';
  import type { AttemptResult, Question } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';
  import CitationChip from './CitationChip.svelte';
  import Notice from './Notice.svelte';

  let {
    question,
    number,
    feedback = null,
    chosen = null,
    error = null
  }: {
    question: Question;
    number: number;
    feedback?: AttemptResult | null;
    chosen?: number | null;
    error?: string | null;
  } = $props();

  let sending = $state(false);
  // Keep this card's result when another question is answered (the action result is per-submit).
  let kept = $state<{ result: AttemptResult; chosen: number | null } | null>(null);
  $effect(() => {
    if (feedback) kept = { result: feedback, chosen };
  });
  let shown = $derived(kept?.result ?? null);
  let image = $derived(mediaUrl(question.image_path));
  const LETTERS = 'ABCDEFGH';

  function optionTone(i: number): string {
    if (!shown) return 'border-line hover:border-line-strong has-[:checked]:border-accent has-[:checked]:bg-accent-soft';
    if (i === shown.correct_index) return 'border-ok bg-ok-soft';
    if (i === kept?.chosen) return 'border-danger bg-danger-soft';
    return 'border-line opacity-70';
  }
</script>

<li class="panel p-5 sm:p-6">
  <p class="label">Q{number}{question.topic ? ` · ${question.topic}` : ''}{question.kind ? ` · ${question.kind}` : ''}</p>
  <p class="mt-2 font-display text-lg leading-snug text-ink">{question.stem}</p>
  {#if image}
    <div class="mt-4 overflow-hidden rounded-xl bg-stage">
      <img src={image} alt="Radiology case for question {number}" class="mx-auto max-h-[60dvh] w-auto" />
    </div>
  {/if}
  <form
    method="POST"
    action="?/answer"
    class="mt-4"
    use:enhance={() => {
      sending = true;
      return async ({ update }) => {
        await update({ invalidateAll: false, reset: false });
        sending = false;
      };
    }}
  >
    <input type="hidden" name="question_id" value={question.id} />
    <fieldset disabled={!!shown}>
      <legend class="sr-only">Options</legend>
      <div class="flex flex-col gap-2">
        {#each question.options as option, i (i)}
          <label
            class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-[0.9375rem] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)] {optionTone(i)}"
          >
            <input type="radio" name="choice" value={i} required class="sr-only" />
            <span class="font-mono text-xs font-semibold text-muted">{LETTERS[i]}</span>
            <span class="text-ink">{option}</span>
          </label>
        {/each}
      </div>
      {#if !shown}
        <button class="btn btn-primary mt-4" type="submit" disabled={sending}>{sending ? 'Checking…' : 'Check answer'}</button>
      {/if}
    </fieldset>
  </form>
  {#if error}<div class="mt-4"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if shown}
    <div class="mt-4 rounded-xl border border-line bg-surface-2/60 p-4">
      <p class="font-semibold {shown.correct ? 'text-ok' : 'text-danger'}">
        {shown.correct ? 'Correct.' : `Not quite — the answer is ${LETTERS[shown.correct_index]}.`}
      </p>
      <p class="mt-1.5 text-[0.9375rem] leading-relaxed text-ink-2">{shown.explanation}</p>
      <div class="mt-3 flex flex-wrap gap-1.5">
        {#each [...shown.citations, ...question.citations] as citation, i (i)}<CitationChip {citation} />{/each}
      </div>
    </div>
  {/if}
</li>
