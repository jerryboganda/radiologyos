<script lang="ts">
  import { invalidate } from '$app/navigation';
  import { untrack } from 'svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import { ExamAutosave, type AutosaveSnapshot, type HttpReply } from '$lib/exam-autosave';
  import { ItemClock } from '$lib/exam-review';
  import { answeredCount, clockOffset, formatClock, isWritten, remainingMs, retryDelay } from '$lib/exam-session';
  import type { ExamView } from '$lib/types/assessment';
  import ExamNavigator from './ExamNavigator.svelte';
  import ExamQuestion from './ExamQuestion.svelte';

  let { exam }: { exam: ExamView } = $props();
  // The page re-mounts this component per exam id; the initial view seeds local state.
  const initial = untrack(() => exam);
  const url = `/exams/${encodeURIComponent(initial.id)}/session`;
  const offset = clockOffset(initial.server_time, Date.now());
  const ids = initial.questions.map((q) => q.id);
  const DEBOUNCE_MS = 800;

  async function call(method: 'GET' | 'PUT' | 'POST', body?: unknown): Promise<HttpReply> {
    try {
      const init: RequestInit = { method, headers: { 'content-type': 'application/json' } };
      if (body !== undefined) init.body = JSON.stringify(body);
      const response = await fetch(url, init);
      return { status: response.status, body: await response.json().catch(() => null) };
    } catch {
      return { status: 0, body: null };
    }
  }

  const initialText = initial.text_answers ?? {};
  const initialConfidence = initial.confidence ?? {};
  let snap = $state<AutosaveSnapshot>({
    answers: { ...initial.answers },
    textAnswers: { ...initialText },
    confidence: { ...initialConfidence },
    revision: initial.revision,
    state: 'idle',
    message: ''
  });
  const autosave = new ExamAutosave(
    {
      answers: initial.answers,
      revision: initial.revision,
      textAnswers: initialText,
      confidence: initialConfidence,
      itemSeconds: initial.item_seconds ?? {}
    },
    {
      save: (revision, answers, text_answers, extras) => call('PUT', { revision, answers, text_answers, ...extras }),
      load: () => call('GET')
    },
    (next) => (snap = next)
  );
  // Active time per item (ADR 0029): runs for the item on screen while the tab is visible.
  const clock = new ItemClock(initial.item_seconds ?? {});
  const TIME_SAVE_MS = 60_000;

  let current = $state(0);
  let now = $state(Date.now());
  let submitting = $state(false);
  let confirming = $state(false);
  let submitError = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;
  let retries = 0;

  let remaining = $derived(remainingMs(initial.deadline_at, offset, now));
  let answered = $derived(answeredCount(ids, snap.answers, snap.textAnswers));
  let question = $derived(initial.questions[current]);
  const hasWritten = initial.questions.some((q) => isWritten(q.type));

  function schedule(delay: number) {
    clearTimeout(timer);
    timer = setTimeout(save, delay);
  }

  function recordTime() {
    autosave.setSeconds(clock.seconds(performance.now()));
  }

  async function save() {
    recordTime();
    const ok = await autosave.flush();
    if (ok) retries = 0;
    else if (snap.state === 'retrying') schedule(retryDelay(retries++));
    else if (snap.state === 'closed') await invalidate('app:exam');
  }

  function choose(option: number | null) {
    if (!question) return;
    autosave.set(question.id, option);
    schedule(DEBOUNCE_MS);
  }

  function rate(level: number | null) {
    if (!question) return;
    autosave.setConfidence(question.id, level);
    schedule(DEBOUNCE_MS);
  }

  function write(text: string) {
    if (!question) return;
    autosave.setText(question.id, text);
    schedule(DEBOUNCE_MS * 2);
  }

  async function submit() {
    if (submitting) return;
    submitting = true;
    submitError = '';
    clearTimeout(timer);
    recordTime();
    await autosave.flush();
    const reply = await call('POST');
    if (reply.status >= 200 && reply.status < 300) {
      await invalidate('app:exam');
      return;
    }
    submitting = false;
    submitError = 'The exam could not be submitted. Check your connection and try again.';
  }

  $effect(() => {
    const tick = setInterval(() => (now = Date.now()), 1000);
    const timeSave = setInterval(() => {
      recordTime();
      if (autosave.hasPending()) schedule(DEBOUNCE_MS);
    }, TIME_SAVE_MS);
    const visibility = () => {
      if (document.hidden) clock.pause(performance.now());
      else if (ids[current]) clock.enter(ids[current], performance.now());
    };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      clearInterval(tick);
      clearInterval(timeSave);
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', visibility);
      clock.pause(performance.now());
    };
  });

  // Moving to another item starts its clock and saves the time spent so far.
  $effect(() => {
    const id = ids[current];
    untrack(() => {
      if (!id || document.hidden) return;
      clock.enter(id, performance.now());
      recordTime();
      if (autosave.hasPending()) schedule(DEBOUNCE_MS);
    });
  });

  $effect(() => {
    if (remaining === 0) untrack(() => void submit());
  });

  const SAVE_TONE: Record<string, string> = { saved: 'text-ok', retrying: 'text-warn', error: 'text-danger', closed: 'text-warn' };
</script>

<div class="sticky top-[calc(3.5rem+env(safe-area-inset-top))] z-10 mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-canvas/95 px-4 py-3 backdrop-blur lg:top-2">
  <p class="text-sm text-ink-2"><span class="font-mono text-ink tabular-nums">{answered}/{ids.length}</span> answered</p>
  <p class="font-mono text-xs {SAVE_TONE[snap.state] ?? 'text-muted'}" role="status">{snap.message}</p>
  {#if remaining !== null}
    <p class="font-mono text-2xl font-semibold tabular-nums {remaining < 5 * 60_000 ? 'text-danger' : 'text-ink'}" aria-label="Time remaining">
      {formatClock(remaining)}
    </p>
  {:else}
    <p class="label">Untimed practice</p>
  {/if}
  <button type="button" class="btn btn-primary" disabled={submitting} onclick={() => (confirming = true)}>
    {submitting ? 'Submitting…' : 'Submit exam'}
  </button>
</div>

{#if submitError}<div class="mb-4"><Notice tone="warn">{submitError}</Notice></div>{/if}
{#if snap.state === 'error'}<div class="mb-4"><Notice tone="warn">{snap.message}</Notice></div>{/if}

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_15rem]">
  <div class="flex min-w-0 flex-col gap-4">
    {#if question}
      <ExamQuestion
        {question}
        number={current + 1}
        selected={snap.answers[question.id]}
        text={snap.textAnswers[question.id] ?? ''}
        confidence={snap.confidence[question.id]}
        disabled={submitting}
        onchoose={choose}
        ontext={write}
        onconfidence={rate}
      />
    {/if}
    <div class="flex justify-between gap-2">
      <button type="button" class="btn btn-ghost" disabled={current === 0} onclick={() => (current -= 1)}>Previous</button>
      <button type="button" class="btn btn-ghost" disabled={current >= ids.length - 1} onclick={() => (current += 1)}>Next</button>
    </div>
  </div>
  <aside class="lg:sticky lg:top-24 lg:self-start">
    <h2 class="label mb-2">Questions</h2>
    <ExamNavigator {ids} answers={snap.answers} textAnswers={snap.textAnswers} {current} onselect={(i) => (current = i)} />
  </aside>
</div>

<ConfirmDialog bind:open={confirming} title="Submit this exam?" confirmLabel="Submit" onconfirm={submit}>
  <p>
    You have answered {answered} of {ids.length} questions.{answered < ids.length ? ' Unanswered questions score zero.' : ''} You cannot change answers after submitting.
    {#if hasWritten}Written answers are marked against their schemes after you submit; results fill in as each is graded.{/if}
  </p>
</ConfirmDialog>
