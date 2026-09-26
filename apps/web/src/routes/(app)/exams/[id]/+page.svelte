<script lang="ts">
  import ExamResults from '$lib/components/exams/ExamResults.svelte';
  import ExamRunner from '$lib/components/exams/ExamRunner.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate } from '$lib/format';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
  let exam = $derived(data.exam);
  let title = $derived(exam.mode === 'practice' ? 'Practice set' : 'Timed exam');
</script>

<svelte:head><title>{title} · radbrain</title></svelte:head>

<PageHeader eyebrow="Exams" {title} description="Started {formatDate(exam.started_at)} · {exam.questions.length} questions">
  {#snippet actions()}<a href="/exams" class="btn btn-ghost">All exams</a>{/snippet}
</PageHeader>

{#if exam.status === 'active'}
  {#key exam.id}<ExamRunner {exam} />{/key}
{:else if exam.result}
  <ExamResults result={exam.result} questions={exam.questions} />
{:else}
  <Notice tone="info">This exam is being graded. Reload in a moment.</Notice>
{/if}
