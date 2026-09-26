<script lang="ts">
  import { enhance } from '$app/forms';
  import CurriculumTree from '$lib/components/knowledge/CurriculumTree.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatDate } from '$lib/format';
  import { CURRICULUM_FILTERS } from '$lib/types/knowledge';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let busy = $state(false);
</script>

<svelte:head><title>Curriculum · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Knowledge"
  title="Curriculum tree"
  description="The systems, topics, and subtopics your mappings, weights, and papers use, tagged by exam. This is a draft built from public syllabi; it becomes yours once you approve it."
/>

<p class="-mt-2 mb-6 text-sm">
  <a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/knowledge">← Back to knowledge</a>
  <span class="mx-2 text-muted">·</span>
  <a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/exams/blueprints">Exam blueprints →</a>
</p>

{#if form}
  <div class="mb-4">
    {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
        >{form.message}</Notice
      >{/if}
  </div>
{/if}

{#if data.problem}
  <LoadIssue problem={data.problem} title="The curriculum is unreachable" icon="knowledge" />
{:else if data.curriculum}
  {@const c = data.curriculum}
  <section class="panel mb-6 p-5 sm:p-6" aria-labelledby="review-heading">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 id="review-heading" class="text-xl font-semibold text-ink">Version {c.version}</h2>
      <StatusBadge status={c.review_status} />
    </div>
    <p class="mt-2 text-sm text-ink-2">
      {c.counts.system ?? 0} systems · {c.counts.topic ?? 0} topics · {c.counts.subtopic ?? 0} subtopics.
      {#if c.decided_at}Last decision {formatDate(c.decided_at)}.{/if}
      {#if c.notes}<span class="block mt-1">Your note: {c.notes}</span>{/if}
    </p>
    <p class="mt-2 text-sm text-muted">{c.source}</p>
    <ul class="mt-2 flex flex-col gap-1 text-sm">
      {#each c.sources as url (url)}<li><a class="break-all text-ink-2 underline underline-offset-2" href={url} rel="noreferrer noopener" target="_blank">{url}</a></li>{/each}
    </ul>
    <form
      method="POST"
      action="?/decide"
      class="mt-4 flex flex-col gap-3"
      use:enhance={() => {
        busy = true;
        return async ({ update }) => {
          await update();
          busy = false;
        };
      }}
    >
      <input type="hidden" name="content_hash" value={c.content_hash} />
      <label class="block">
        <span class="label">Notes (required to reject)</span>
        <textarea name="notes" maxlength="2000" rows="2" class="field mt-1.5"></textarea>
      </label>
      <div class="flex flex-wrap gap-2">
        <button class="btn btn-primary" name="decision" value="approved" disabled={busy}>Approve this version</button>
        <button class="btn btn-ghost" name="decision" value="rejected" disabled={busy}>Reject</button>
      </div>
      <p class="label">Only the account owner or an admin can decide. Weights stay separate: approve them on the knowledge page.</p>
    </form>
  </section>

  <form method="GET" class="mb-4 flex flex-wrap items-end gap-2">
    <label class="block">
      <span class="label">Show exam</span>
      <select name="exam" class="field mt-1.5">
        <option value="">All exams</option>
        {#each CURRICULUM_FILTERS as option (option.value)}<option value={option.value} selected={data.filter === option.value}>{option.label}</option>{/each}
      </select>
    </label>
    <button class="btn btn-ghost" type="submit">Filter</button>
  </form>
  <CurriculumTree systems={c.systems} />
{/if}
