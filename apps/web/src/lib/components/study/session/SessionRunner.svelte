<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import ReviewDeck from '$lib/components/study/ReviewDeck.svelte';
  import { isFinished, progressPercent, selectedStep, stepTitle } from '$lib/session';
  import type { StudySession } from '$lib/types/session';
  import LearnStep from './LearnStep.svelte';
  import SbaBlock from './SbaBlock.svelte';
  import SessionSummary from './SessionSummary.svelte';
  import VivaStep from './VivaStep.svelte';

  let {
    session,
    error = null,
    reviewError = null,
    scheduledDays = null
  }: { session: StudySession; error?: string | null; reviewError?: string | null; scheduledDays?: number | null } = $props();

  let requested = $state<number | null>(null);
  let busy = $state(false);
  let step = $derived(selectedStep(session, requested));
  let done = $derived(progressPercent(session));
  let planned = $derived(session.steps.reduce((sum, s) => sum + s.minutes, 0));

  const INTRO: Record<string, string> = {
    review: 'Cards due today, oldest first. Rate each one honestly; missed cards come back soon.',
    learn: 'Read these cited passages and figures for today’s priority topic.',
    test: 'A timed block of single-best-answer questions. Missed items return as cards and re-tests.',
    viva: 'One open question. Answer as you would to the examiner.'
  };
  const START: Record<string, string> = { review: 'Start reviewing', learn: 'Start reading', test: 'Start the timed block', viva: 'Start the viva' };
  const STATUS: Record<string, string> = { pending: 'not started', active: 'in progress', done: 'done', skipped: 'skipped' };

  function submitting(resume = false) {
    return () => {
      busy = true;
      return async ({ update }: { update: (options?: { reset?: boolean }) => Promise<void> }) => {
        await update({ reset: false });
        busy = false;
        if (resume) requested = null;
      };
    };
  }
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="session-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="session-heading" class="text-xl font-semibold text-ink">Today’s session</h2>
    <p class="label">{session.progress.done}/{session.progress.total} steps · {planned} min planned</p>
  </div>
  <div class="mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-label="Session progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={done}>
    <div class="h-full bg-accent transition-[width]" style="width: {done}%"></div>
  </div>

  {#if session.steps.length === 0}
    <p class="mt-5 text-sm text-ink-2">
      Nothing to run yet. Generate cards or SBA questions from your library, and map sources to the curriculum, so today’s session has cited material.
    </p>
  {:else}
    <ol class="mt-4 flex flex-wrap gap-2" aria-label="Steps">
      {#each session.steps as s (s.step_no)}
        <li>
          <button
            type="button"
            aria-current={step?.step_no === s.step_no ? 'step' : undefined}
            onclick={() => (requested = s.step_no)}
            class="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm {step?.step_no === s.step_no ? 'border-accent bg-accent-soft text-ink' : 'border-line text-ink-2 hover:border-line-strong'}"
          >
            {#if s.status === 'done'}<Icon name="check" size={14} class="text-ok" />{:else if s.status === 'skipped'}<Icon name="x" size={14} class="text-muted" />{:else}<span class="font-mono text-xs text-muted">{s.step_no}</span>{/if}
            {stepTitle(s)}
            <span class="sr-only">({STATUS[s.status]})</span>
          </button>
        </li>
      {/each}
    </ol>
  {/if}

  {#if error}<div class="mt-4"><Notice tone="warn">{error}</Notice></div>{/if}

  {#if session.status === 'completed'}
    <div class="mt-5"><SessionSummary summary={session.summary} /></div>
  {:else if step}
    <div class="mt-5 border-t border-line pt-5">
      <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 class="font-display text-lg text-ink">{stepTitle(step)}</h3>
        <p class="label">{step.minutes} min · {STATUS[step.status]}</p>
      </div>
      {#if step.status === 'pending'}
        <p class="text-sm text-ink-2">{INTRO[step.kind]}</p>
        <form method="POST" action="?/stepStart" class="mt-4" use:enhance={submitting()}>
          <input type="hidden" name="session_id" value={session.id} />
          <input type="hidden" name="step_no" value={step.step_no} />
          <button class="btn btn-primary" disabled={busy}>{START[step.kind]}</button>
        </form>
      {:else if step.kind === 'review' && step.review}
        <p class="label mb-2">{step.review.reviewed}/{step.review.total} reviewed</p>
        <ReviewDeck embedded cards={step.review.cards} error={reviewError} {scheduledDays} />
      {:else if step.kind === 'learn' && step.learn}
        <LearnStep learn={step.learn} />
      {:else if step.kind === 'test' && step.test}
        <SbaBlock sessionId={session.id} {step} serverTime={session.server_time} />
      {:else if step.kind === 'viva' && step.viva}
        <VivaStep sessionId={session.id} {step} />
      {/if}

      <div class="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        {#if !isFinished(step)}
          <form method="POST" action="?/stepComplete" class="flex flex-wrap gap-2" use:enhance={submitting(true)}>
            <input type="hidden" name="session_id" value={session.id} />
            <input type="hidden" name="step_no" value={step.step_no} />
            <button class="btn btn-primary" disabled={busy}>Mark step done</button>
            <button class="btn btn-ghost" name="skip" value="true" disabled={busy}>Skip</button>
          </form>
        {:else if session.current_step !== null}
          <button type="button" class="btn btn-primary" onclick={() => (requested = null)}>Continue to the next step</button>
        {/if}
        <form method="POST" action="?/sessionComplete" class="ml-auto" use:enhance={submitting(true)}>
          <input type="hidden" name="session_id" value={session.id} />
          <button class="btn {session.current_step === null ? 'btn-primary' : 'btn-ghost'}" disabled={busy}>
            {session.current_step === null ? 'Finish today’s session' : 'Finish early'}
          </button>
        </form>
      </div>
    </div>
  {/if}
  <p class="mt-4 text-xs text-muted">{session.notice}</p>
</section>
