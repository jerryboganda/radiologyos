<script lang="ts">
  import ExamResults from '$lib/components/exams/ExamResults.svelte';
  import ExamRunner from '$lib/components/exams/ExamRunner.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate } from '$lib/format';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let exam = $derived(data.exam);
  let title = $derived(exam.mode === 'practice' ? 'Practice set' : 'Timed exam');
</script>

<svelte:head><title>{title} · radbrain</title></svelte:head>

<PageHeader eyebrow="Exams" {title} description="Started {formatDate(exam.started_at)} · {exam.questions.length} questions">
  {#snippet actions()}<a href="/exams" class="btn btn-ghost">All exams</a>{/snippet}
</PageHeader>

{#if form?.disputeError}<div class="mb-4"><Notice tone="warn">{form.disputeError}</Notice></div>{/if}
{#if form?.disputed}<div class="mb-4"><Notice tone="ok">Dispute sent to the owner’s review queue.</Notice></div>{/if}

{#if exam.status === 'active'}
  {#key exam.id}<ExamRunner {exam} />{/key}
{:else if exam.result}
  <ExamResults result={exam.result} questions={exam.questions} disputes={data.disputes} />
{:else}
  <Notice tone="info">This exam is being graded. Reload in a moment.</Notice>
{/if}
