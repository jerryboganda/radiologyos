<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatDate } from '$lib/format';
  import { EXAM_TARGETS } from '$lib/types/study';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let mode = $state<'exam' | 'practice'>('exam');
  let creating = $state(false);
</script>

<svelte:head><title>Exams · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Exams"
  title="Timed mock exams"
  description="Papers are assembled from your checked SBA questions. The server keeps the clock, answers autosave as you go, and results break down by topic with cited keys."
/>

<div class="flex flex-col gap-8">
  <section class="panel p-5 sm:p-6" aria-labelledby="new-heading">
    <h2 id="new-heading" class="text-xl font-semibold text-ink">Start a paper</h2>
    <form
      method="POST"
      action="?/create"
      class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      use:enhance={() => {
        creating = true;
        return async ({ update }) => {
          await update();
          creating = false;
        };
      }}
    >
      <fieldset class="sm:col-span-2 lg:col-span-3">
        <legend class="label">Mode</legend>
        <div class="mt-1.5 flex gap-2">
          {#each [['exam', 'Timed exam'], ['practice', 'Untimed practice']] as [value, label] (value)}
            <label class="cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink">
              <input type="radio" name="mode" {value} bind:group={mode} class="sr-only" />{label}
            </label>
          {/each}
        </div>
      </fieldset>
      <label class="block">
        <span class="label">Exam</span>
        <select name="exam_target" class="field mt-1.5">
          <option value="">Any</option>
          {#each EXAM_TARGETS as target (target.value)}<option value={target.value}>{target.label}</option>{/each}
        </select>
      </label>
      <label class="block">
        <span class="label">Topic (optional)</span>
        <input name="topic" maxlength="200" class="field mt-1.5" />
      </label>
      <label class="block">
        <span class="label">Questions</span>
        <input name="count" type="number" min="1" max="200" value="20" required class="field mt-1.5 font-mono" />
      </label>
      {#if mode === 'exam'}
        <label class="block">
          <span class="label">Time limit (minutes)</span>
          <input name="time_limit_minutes" type="number" min="1" max="300" value="30" required class="field mt-1.5 font-mono" />
        </label>
      {/if}
      <div class="flex items-end sm:col-span-2 lg:col-span-3">
        <button class="btn btn-primary" type="submit" disabled={creating}>{creating ? 'Assembling…' : 'Start'}</button>
      </div>
    </form>
    {#if form?.error}<div class="mt-4"><Notice tone="warn">{form.error}</Notice></div>{/if}
  </section>

  <section aria-labelledby="recent-heading">
    <h2 id="recent-heading" class="mb-3 text-xl font-semibold text-ink">Recent on this device</h2>
    {#if data.exams.length === 0}
      <p class="text-sm text-muted">No exams yet. Generate SBA questions first, then start a paper.</p>
    {:else}
      <ul class="grid gap-3 sm:grid-cols-2">
        {#each data.exams as exam (exam.id)}
          <li>
            <a href="/exams/{exam.id}" class="panel flex items-center justify-between gap-3 p-4 hover:border-accent">
              <span>
                <span class="block font-medium text-ink">{exam.mode === 'practice' ? 'Practice set' : 'Timed exam'} · {exam.questions} questions</span>
                <span class="label">{formatDate(exam.started_at)}{exam.percent !== null ? ` · ${exam.percent}%` : ''}</span>
              </span>
              <StatusBadge status={exam.status} />
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>
