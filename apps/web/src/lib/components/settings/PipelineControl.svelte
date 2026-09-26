<script lang="ts">
  import { enhance } from '$app/forms';
  import type { SubmitFunction } from '@sveltejs/kit';
  import type { LoadProblem } from '$lib/api-state';
  import { awaitingText, awaitingTotal, pipelineProgress, pipelineSummary } from '$lib/pipeline-control';
  import type { PipelineStatus } from '$lib/types/admin';
  import LoadIssue from '../LoadIssue.svelte';

  let { status, problem }: { status: PipelineStatus | null; problem: LoadProblem | null } = $props();
  const uid = $props.id();

  // The server renders in UTC; the browser switches the resume time to local time.
  let timeZone = $state<string | undefined>('UTC');
  let busy = $state('');
  let understood = $state(false);
  $effect(() => {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  });

  let summary = $derived(status ? pipelineSummary(status, timeZone) : null);
  let progress = $derived(status ? pipelineProgress(status) : null);
  let waiting = $derived(status ? awaitingTotal(status) : 0);

  const DOT = { ok: 'bg-ok', warn: 'bg-warn', idle: 'bg-muted' };
  const PILL = { ok: 'bg-ok-soft text-ok', warn: 'bg-warn-soft text-warn', idle: 'bg-surface-2 text-ink-2' };

  function submitting(name: string): SubmitFunction {
    return () => {
      busy = name;
      return async ({ result, update }) => {
        await update();
        if (name === 'approve' && result.type === 'success') understood = false;
        busy = '';
      };
    };
  }
</script>

<p class="mt-1 mb-5 text-sm text-ink-2">
  Reads your uploaded books page by page and turns them into notes. You can pause at any time; finished work is kept.
</p>

{#if status && summary && progress}
  <div class="flex flex-wrap items-center justify-between gap-3">
    <p class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium {PILL[summary.tone]}" role="status">
      <span class="h-2 w-2 shrink-0 rounded-full {DOT[summary.tone]}" aria-hidden="true"></span>{summary.text}
    </p>
    {#if status.paused === 'manual'}
      <form method="POST" action="?/resumePipeline" use:enhance={submitting('resume')}>
        <button class="btn btn-primary" type="submit" disabled={busy !== ''}>{busy === 'resume' ? 'Resuming…' : 'Resume'}</button>
      </form>
    {:else}
      <form method="POST" action="?/pausePipeline" use:enhance={submitting('pause')}>
        <button class="btn btn-ghost" type="submit" disabled={busy !== ''}>{busy === 'pause' ? 'Pausing…' : 'Pause'}</button>
      </form>
    {/if}
  </div>
  {#if status.paused === 'quota'}
    <p class="mt-2 text-xs text-muted">It carries on by itself when the quota resets. Pause now to keep it stopped after that.</p>
  {/if}

  <dl class="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
    <div>
      <dt class="label">Pages read</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{progress.pagesRead}<span class="text-sm text-muted"> / {progress.pagesTotal}</span></dd>
    </div>
    <div>
      <dt class="label">Pages failed</dt>
      <dd class="mt-1 font-mono text-lg {progress.pagesFailed > 0 ? 'text-warn' : 'text-ink'}">{progress.pagesFailed}</dd>
    </div>
    <div>
      <dt class="label">Books in progress</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{progress.booksActive}</dd>
    </div>
    <div>
      <dt class="label">Notes done</dt>
      <dd class="mt-1 font-mono text-lg text-ink">{progress.unitsDone}</dd>
    </div>
  </dl>
  {#if progress.booksFailed > 0 || progress.unitsFailed > 0}
    <p class="mt-3 text-xs text-muted">
      {progress.booksFailed} book{progress.booksFailed === 1 ? '' : 's'} and {progress.unitsFailed} note{progress.unitsFailed === 1 ? '' : 's'} could not
      be finished.
    </p>
  {/if}

  {#if waiting > 0}
    <div class="mt-6 rounded-xl border border-warn/40 p-4">
      <p class="text-sm font-medium text-ink">{waiting} item{waiting === 1 ? '' : 's'} need your OK</p>
      <p class="mt-1 text-sm text-ink-2">
        GPT-6 Luna and Sol could not finish {awaitingText(status)}. Claude Opus can try them, using your Claude quota. Or dismiss them to skip.
      </p>
      <form method="POST" action="?/approvePipeline" class="mt-4 flex flex-col gap-3" use:enhance={submitting('approve')}>
        <label for="{uid}-confirm" class="flex items-start gap-2 text-sm text-ink">
          <input id="{uid}-confirm" type="checkbox" name="confirm" value="yes" bind:checked={understood} class="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" />
          I understand this uses my Claude quota
        </label>
        <div>
          <button class="btn btn-primary" type="submit" disabled={!understood || busy !== ''}>
            {busy === 'approve' ? 'Sending…' : `Approve ${waiting} item${waiting === 1 ? '' : 's'} for Claude Opus`}
          </button>
        </div>
      </form>
      <form method="POST" action="?/dismissPipeline" class="mt-2" use:enhance={submitting('dismiss')}>
        <button class="btn btn-ghost" type="submit" disabled={busy !== ''}>{busy === 'dismiss' ? 'Dismissing…' : 'Dismiss'}</button>
      </form>
    </div>
  {/if}
{:else if problem}
  <LoadIssue compact {problem} title="Library processing is unreachable" icon="signal" />
{/if}
