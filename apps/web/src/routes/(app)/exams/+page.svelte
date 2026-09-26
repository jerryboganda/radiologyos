<script lang="ts">
  import { enhance } from '$app/forms';
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Exams · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Exams"
  title="Timed mock exams"
  description="Full-length, timed papers in the FCPS-II format. Autosaved as you go; results broken down by topic, with citations for every answer."
/>

{#if form?.error}<div class="mb-5"><Notice tone="warn">{form.error}</Notice></div>{/if}

{#if data.detail}
  <Notice tone="danger">{data.detail}</Notice>
{:else if !data.online}
  <ComingOnline
    title="Mock exams are coming online"
    description="Timed papers with autosave and cited explanations will appear here once the exam service is deployed."
    endpoints={['/v1/exams', '/v1/exams/{id}/start']}
    icon="exams"
  />
{:else if data.exams.length === 0}
  <div class="panel px-6 py-12 text-center">
    <p class="font-display text-xl text-ink">No mock exams yet.</p>
    <p class="mt-2 text-sm text-muted">Mocks are assembled once enough cited questions exist across the blueprint.</p>
  </div>
{:else}
  <ul class="grid gap-4 sm:grid-cols-2">
    {#each data.exams as exam (exam.id)}
      <li class="panel flex flex-col p-5">
        <div class="flex items-start justify-between gap-3">
          <h2 class="text-lg font-semibold text-ink">{exam.title}</h2>
          <StatusBadge status={exam.status} />
        </div>
        <p class="label mt-2">{exam.kind} · {exam.question_count} questions · {exam.minutes} min</p>
        {#if exam.status === 'submitted' && exam.score != null}
          <p class="mt-3 font-display text-3xl text-ink">{Math.round(exam.score * 100)}<span class="text-base text-muted">% scored</span></p>
        {/if}
        <form method="POST" action="?/start" use:enhance class="mt-auto pt-4">
          <input type="hidden" name="exam_id" value={exam.id} />
          {#if exam.status !== 'submitted'}
            <button class="btn btn-primary" type="submit">{exam.status === 'in_progress' ? 'Resume' : 'Start'}</button>
          {/if}
        </form>
      </li>
    {/each}
  </ul>
{/if}
