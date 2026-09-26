<script lang="ts">
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import QuestionCard from '$lib/components/QuestionCard.svelte';
  import GenerateQuestions from '$lib/components/questions/GenerateQuestions.svelte';
  import QuestionTabs from '$lib/components/questions/QuestionTabs.svelte';
  import { QUESTION_TYPES } from '$lib/types/assessment';
  import { EXAM_TARGETS } from '$lib/types/study';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let generated = $derived(form && 'generated' in form ? form.generated : null);
  let summary = $derived(
    generated
      ? `Created ${generated.created} question${generated.created === 1 ? '' : 's'} from ${generated.excerpts} excerpts` +
          (generated.drafts ? `; ${generated.drafts} kept as drafts for review` : '') +
          (generated.duplicates ? `; ${generated.duplicates} skipped as near-duplicates of your bank` : '') +
          (generated.rejected ? `; ${generated.rejected} rejected by the checker` : '') +
          '.'
      : null
  );
</script>

<svelte:head><title>Questions · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Questions"
  title="Practice questions"
  description="SBA, SEQ, image cases, and viva prompts generated from and cited to your sources. SBAs are marked instantly; written answers are graded against a fixed marking scheme."
/>

<QuestionTabs current="bank" />

<div class="flex flex-col gap-6">
  <GenerateQuestions sources={data.sources} error={form && 'generateError' in form ? form.generateError : null} {summary} />

  <form method="GET" class="flex flex-wrap items-end gap-3" aria-label="Filter questions">
    <label class="block">
      <span class="label">Type</span>
      <select name="type" class="field mt-1.5" value={data.filters.type ?? ''}>
        <option value="">All types</option>
        {#each QUESTION_TYPES as type (type.value)}<option value={type.value}>{type.label}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Exam</span>
      <select name="exam_target" class="field mt-1.5" value={data.filters.exam_target ?? ''}>
        <option value="">All exams</option>
        {#each EXAM_TARGETS as target (target.value)}<option value={target.value}>{target.label}</option>{/each}
      </select>
    </label>
    <label class="block">
      <span class="label">Topic</span>
      <input name="topic" value={data.filters.topic ?? ''} maxlength="200" class="field mt-1.5" />
    </label>
    <button class="btn btn-ghost" type="submit">Filter</button>
  </form>

  {#if data.problem}
    <LoadIssue problem={data.problem} title="The question bank is unreachable" icon="questions" />
  {:else if data.questions.length === 0}
    <div class="panel px-6 py-12 text-center">
      <p class="font-display text-xl text-ink">No questions match.</p>
      <p class="mt-2 text-sm text-muted">Generate some from a topic or your processed sources above.</p>
    </div>
  {:else}
    <ol class="flex flex-col gap-5">
      {#each data.questions as question, i (question.id)}
        {@const mine = form && 'questionId' in form && form.questionId === question.id}
        <QuestionCard
          {question}
          number={i + 1}
          feedback={mine && 'result' in form ? form.result : null}
          chosen={mine && 'chosen' in form ? form.chosen : null}
          error={mine && 'error' in form ? form.error : null}
        />
      {/each}
    </ol>
  {/if}
</div>
