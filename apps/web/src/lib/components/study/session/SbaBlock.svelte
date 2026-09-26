<script lang="ts">
  import { enhance } from '$app/forms';
  import { untrack } from 'svelte';
  import Kbd from '$lib/components/Kbd.svelte';
  import SbaFeedback from '$lib/components/questions/SbaFeedback.svelte';
  import { clockOffset, formatClock, remainingMs } from '$lib/exam-session';
  import { optionLetter } from '$lib/questions';
  import { CONFIDENCE, nextUnanswered } from '$lib/session';
  import { sbaKey } from '$lib/shortcuts';
  import type { SbaBlockView, SessionStep } from '$lib/types/session';
  import { mediaUrl } from '$lib/viewer';

  let { sessionId, step, serverTime }: { sessionId: string; step: SessionStep; serverTime: string } = $props();
  let block = $derived(step.test as SbaBlockView);
  const offset = untrack(() => clockOffset(serverTime, Date.now()));

  let pinned = $state<string | null>(null);
  let choice = $state<number | null>(null);
  let confidence = $state<number | null>(null);
  let sending = $state(false);
  let answerForm = $state<HTMLFormElement | null>(null);
  let now = $state(Date.now());

  let currentId = $derived(pinned ?? nextUnanswered(block));
  let question = $derived(block.questions.find((q) => q.id === currentId) ?? null);
  let feedback = $derived(block.results.find((r) => r.question_id === currentId) ?? null);
  let remaining = $derived(remainingMs(step.deadline_at, offset, now));
  let timeUp = $derived(remaining === 0);
  let image = $derived(mediaUrl(question?.figure_image_path));

  $effect(() => {
    void currentId;
    choice = null;
    confidence = null;
  });

  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(tick);
  });

  function next() {
    pinned = nextUnanswered(block, currentId);
  }

  function onKey(event: KeyboardEvent) {
    if (!question || sending) return;
    const action = sbaKey(event, question.options.length);
    if (!action) return;
    if (action.kind === 'submit') {
      event.preventDefault();
      if (feedback) next();
      else if (choice !== null && !timeUp) answerForm?.requestSubmit();
    } else if (!feedback && !timeUp) {
      event.preventDefault();
      if (action.kind === 'choose') choice = action.option;
      else confidence = action.level;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line px-4 py-2.5">
  <p class="text-sm text-ink-2">
    <span class="font-mono text-ink tabular-nums">{block.answered}/{block.total}</span> answered ·
    <span class="font-mono tabular-nums">{block.correct}</span> correct{block.retests ? ` · ${block.retests} re-test${block.retests === 1 ? '' : 's'} of earlier misses` : ''}
  </p>
  {#if remaining !== null}
    <p class="font-mono text-xl font-semibold tabular-nums {remaining < 60_000 ? 'text-danger' : 'text-ink'}" aria-label="Time remaining">
      {formatClock(remaining)}
    </p>
  {/if}
</div>

{#if timeUp && !feedback}
  <p class="mt-4 text-sm text-warn" role="status">Time is up for this block. Mark the step done to see your summary.</p>
{:else if !question}
  <p class="mt-4 text-sm text-ink-2">All {block.total} questions answered. Continue to the next step.</p>
{:else}
  <article class="mt-4" aria-labelledby="sba-{question.id}">
    <p class="label">Question {block.questions.indexOf(question) + 1} of {block.total}{question.topic ? ` · ${question.topic}` : ''}</p>
    <p id="sba-{question.id}" class="mt-2 font-display text-lg leading-snug whitespace-pre-line text-ink">{question.stem}</p>
    {#if image}
      <div class="mt-3 overflow-hidden rounded-xl bg-stage"><img src={image} alt="Radiology figure for this question" class="mx-auto max-h-[50dvh] w-auto" /></div>
    {/if}
    {#if feedback}
      <div class="mt-4">
        <SbaFeedback correct={feedback.correct} keyIndex={feedback.key} explanation={feedback.explanation} options={feedback.option_explanations} citations={feedback.citations} />
      </div>
      <button type="button" class="btn btn-primary mt-4" aria-keyshortcuts="Enter" onclick={next}>
        {nextUnanswered(block, currentId) ? 'Next question' : 'Done'} <Kbd key="Enter" class="ml-1" />
      </button>
    {:else}
      <form
        method="POST"
        action="?/stepAnswer"
        bind:this={answerForm}
        use:enhance={() => {
          sending = true;
          pinned = currentId;
          return async ({ update }) => {
            await update({ reset: false });
            sending = false;
          };
        }}
      >
        <input type="hidden" name="session_id" value={sessionId} />
        <input type="hidden" name="step_no" value={step.step_no} />
        <input type="hidden" name="question_id" value={question.id} />
        <fieldset class="mt-4" disabled={sending}>
          <legend class="sr-only">Options (keys A to {optionLetter(question.options.length - 1)})</legend>
          <div class="flex flex-col gap-2">
            {#each question.options as option, i (i)}
              <label class="flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-[0.9375rem] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)] {choice === i ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}">
                <input type="radio" name="selected_option" value={i} checked={choice === i} aria-keyshortcuts={optionLetter(i)} onchange={() => (choice = i)} class="sr-only" />
                <Kbd key={optionLetter(i)} class="mt-0.5" />
                <span class="text-ink">{option}</span>
              </label>
            {/each}
          </div>
        </fieldset>
        <fieldset class="mt-4 flex flex-wrap items-center gap-2" disabled={sending}>
          <legend class="label mb-1.5 w-full">How sure are you? (optional)</legend>
          {#each CONFIDENCE as c (c.level)}
            <label class="flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)] {confidence === c.level ? 'border-accent bg-accent-soft text-ink' : 'border-line text-ink-2'}">
              <input type="radio" name="confidence" value={c.level} checked={confidence === c.level} aria-keyshortcuts={String(c.level)} onchange={() => (confidence = c.level)} class="sr-only" />
              <Kbd key={String(c.level)} />{c.label}
            </label>
          {/each}
        </fieldset>
        <button type="submit" class="btn btn-primary mt-4" disabled={choice === null || sending} aria-keyshortcuts="Enter">
          {sending ? 'Checking…' : 'Submit answer'} <Kbd key="Enter" class="ml-1" />
        </button>
      </form>
    {/if}
  </article>
{/if}
