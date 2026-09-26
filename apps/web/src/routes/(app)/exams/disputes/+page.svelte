<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationList from '$lib/components/CitationList.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate } from '$lib/format';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let busy = $state(false);
  const DONE: Record<string, string> = {
    accepted: 'Accepted: the mark was raised and the exam total recomputed (audited).',
    rejected: 'Rejected: the original mark stands.'
  };
</script>

<svelte:head><title>Grade disputes · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Exams"
  title="Grade disputes"
  description="Disputed marks on auto-graded written answers. Read the answer against the cited marking point, then accept (the score is adjusted and audited) or reject."
>
  {#snippet actions()}<a href="/exams" class="btn btn-ghost">All exams</a>{/snippet}
</PageHeader>

{#if form && 'resolved' in form && form.resolved}
  <div class="mb-4"><Notice tone="ok">{DONE[form.resolved] ?? 'Saved.'}</Notice></div>
{/if}
{#if form && 'error' in form && form.error}<div class="mb-4"><Notice tone="warn">{form.error}</Notice></div>{/if}

{#if data.forbidden}
  <Notice tone="info">Only the owner or an admin can review grade disputes.</Notice>
{:else if data.problem}
  <LoadIssue problem={data.problem} title="The dispute queue is unreachable" icon="questions" />
{:else if data.disputes.length === 0}
  <div class="panel px-6 py-12 text-center">
    <p class="font-display text-xl text-ink">No open disputes.</p>
    <p class="mt-2 text-sm text-muted">Disputes appear here when a mark on a written answer is challenged from an exam's results.</p>
  </div>
{:else}
  <ol class="flex flex-col gap-5">
    {#each data.disputes as d (d.id)}
      <li class="panel flex flex-col gap-3 p-5">
        <p class="label">{d.topic || 'Written item'} · point {d.point_index + 1} · {d.awarded_before}/{d.marks} · raised {formatDate(d.created_at)}</p>
        {#if d.stem}<p class="leading-snug whitespace-pre-line text-ink">{d.stem}</p>{/if}
        <div class="rounded-xl border border-line bg-surface-2/60 p-3 text-sm">
          <p class="font-semibold text-ink">{d.point}</p>
          {#if d.justification}<p class="mt-1 text-ink-2">Grader: {d.justification}</p>{/if}
          <CitationList citations={d.citations} class="mt-2" />
        </div>
        <details class="rounded-xl border border-line px-4 py-3 text-sm" open>
          <summary class="cursor-pointer text-ink-2">Candidate’s answer and reason</summary>
          <p class="mt-2 whitespace-pre-line text-ink">{d.answer_text}</p>
          <p class="mt-2 text-ink-2"><span class="label">Reason</span> {d.reason}</p>
        </details>
        <form
          method="POST"
          action="?/resolve"
          class="grid gap-2 sm:grid-cols-[8rem_1fr_auto_auto] sm:items-end"
          use:enhance={() => {
            busy = true;
            return async ({ update }) => {
              await update();
              busy = false;
            };
          }}
        >
          <input type="hidden" name="dispute_id" value={d.id} />
          <label class="block">
            <span class="label">New mark</span>
            <input name="awarded" type="number" step="0.25" min="0.25" max={d.marks} placeholder={String(d.marks)} class="field mt-1 font-mono" />
          </label>
          <label class="block min-w-0">
            <span class="label">Note (optional)</span>
            <input name="note" maxlength="2000" class="field mt-1" />
          </label>
          <button class="btn btn-primary" type="submit" name="action" value="accept" disabled={busy}>Accept</button>
          <button class="btn btn-ghost" type="submit" name="action" value="reject" disabled={busy}>Reject</button>
        </form>
      </li>
    {/each}
  </ol>
{/if}
