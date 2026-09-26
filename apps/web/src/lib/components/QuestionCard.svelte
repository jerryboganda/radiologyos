<script lang="ts">
  import { enhance } from '$app/forms';
  import { optionLetter } from '$lib/questions';
  import type { AttemptOut, QuestionPublic } from '$lib/types/assessment';
  import { mediaUrl } from '$lib/viewer';
  import Notice from './Notice.svelte';
  import SbaFeedback from './questions/SbaFeedback.svelte';
  import WrittenFeedback from './questions/WrittenFeedback.svelte';

  let {
    question,
    number,
    feedback = null,
    chosen = null,
    error = null
  }: {
    question: QuestionPublic;
    number: number;
    feedback?: AttemptOut | null;
    chosen?: number | null;
    error?: string | null;
  } = $props();

  let sending = $state(false);
  // Keep this card's result when another question is answered (the action result is per-submit).
  let kept = $state<{ result: AttemptOut; chosen: number | null } | null>(null);
  $effect(() => {
    if (feedback) kept = { result: feedback, chosen };
  });
  let shown = $derived(kept?.result ?? null);
  let image = $derived(mediaUrl(question.figure_image_path));
  let isSba = $derived(question.type === 'sba' && question.options.length > 0);
  let isRecall = $derived(question.type === 'rapid_recall');

  function optionTone(i: number): string {
    if (!shown) return 'border-line hover:border-line-strong has-[:checked]:border-accent has-[:checked]:bg-accent-soft';
    if (i === shown.key) return 'border-ok bg-ok-soft';
    if (i === kept?.chosen) return 'border-danger bg-danger-soft';
    return 'border-line opacity-70';
  }
</script>

<li class="panel p-5 sm:p-6">
  <p class="label">Q{number} · {question.type.replace(/_/g, ' ')}{question.topic ? ` · ${question.topic}` : ''}{question.exam_tags.length ? ` · ${question.exam_tags.join(', ')}` : ''}</p>
  <p class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{question.stem}</p>
  {#if image}
    <div class="mt-4 overflow-hidden rounded-xl bg-stage">
      <img src={image} alt="Radiology image for question {number}" class="mx-auto max-h-[60dvh] w-auto" />
    </div>
    <p class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {#if question.stages?.length}
        <a class="link" href="/viva?kind=image_case&question={question.id}">Practise as a staged station</a>
      {/if}
      {#if question.figure_id}<a class="link" href="/viva?figure={question.figure_id}">Viva on this image</a>{/if}
    </p>
  {/if}
  {#if isRecall}
    <p class="mt-4 text-sm text-muted">Rapid-recall items are practised through card review on Today.</p>
  {:else}
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
      <fieldset disabled={!!shown || sending}>
        <legend class="sr-only">{isSba ? 'Options' : 'Your answer'}</legend>
        {#if isSba}
          <div class="flex flex-col gap-2">
            {#each question.options as option, i (i)}
              <label
                class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-[0.9375rem] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)] {optionTone(i)}"
              >
                <input type="radio" name="choice" value={i} required class="sr-only" />
                <span class="font-mono text-xs font-semibold text-muted">{optionLetter(i)}</span>
                <span class="text-ink">{option}</span>
              </label>
            {/each}
          </div>
        {:else}
          <textarea name="answer_text" rows="6" required maxlength="8000" class="field resize-y" placeholder="Write your answer as you would in the exam…"></textarea>
        {/if}
        {#if !shown}
          <button class="btn btn-primary mt-4" type="submit" disabled={sending}>
            {sending ? (isSba ? 'Checking…' : 'Grading against the marking scheme…') : isSba ? 'Check answer' : 'Submit for grading'}
          </button>
        {/if}
      </fieldset>
    </form>
  {/if}
  {#if error}<div class="mt-4"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if shown}
    <div class="mt-4">
      {#if shown.type === 'sba'}
        <SbaFeedback
          correct={shown.correct}
          keyIndex={shown.key}
          explanation={shown.explanation}
          options={shown.option_explanations}
          citations={shown.citations}
        />
      {:else}
        <WrittenFeedback result={shown} />
      {/if}
    </div>
  {/if}
</li>
