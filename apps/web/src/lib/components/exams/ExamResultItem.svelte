<script lang="ts">
  import SbaFeedback from '$lib/components/questions/SbaFeedback.svelte';
  import WrittenFeedback from '$lib/components/questions/WrittenFeedback.svelte';
  import { optionLetter } from '$lib/questions';
  import { STAGE_LABELS, type Stage } from '$lib/viva';
  import type { ExamResultItem, QuestionPublic, SbaResultItem, WrittenResultItem } from '$lib/types/assessment';

  let { item, number, question }: { item: ExamResultItem; number: number; question: QuestionPublic | undefined } = $props();

  const isWrittenItem = (value: ExamResultItem): value is WrittenResultItem =>
    value.type === 'seq' || value.type === 'image_case' || value.type === 'viva';
  let written = $derived(isWrittenItem(item) ? item : null);
  let sba = $derived(isWrittenItem(item) ? null : (item as SbaResultItem));
  const TYPE_LABEL: Record<string, string> = { seq: 'SEQ', image_case: 'Image case', viva: 'Viva' };
</script>

<li class="panel p-5">
  {#if sba}
    <p class="label">Q{number}{sba.topic ? ` · ${sba.topic}` : ''} · your answer {optionLetter(sba.selected_option)}</p>
  {:else if written}
    <p class="label">Q{number} · {TYPE_LABEL[written.type] ?? written.type}{written.topic ? ` · ${written.topic}` : ''}</p>
  {/if}
  {#if question}<p class="mt-2 leading-snug whitespace-pre-line text-ink">{question.stem}</p>{/if}
  <div class="mt-3">
    {#if sba}
      <SbaFeedback
        correct={sba.correct}
        keyIndex={sba.key}
        explanation={sba.explanation}
        options={sba.option_explanations}
        citations={sba.citations}
      />
    {:else if written}
      {#if written.answer_text}
        <details class="mb-3 rounded-xl border border-line px-4 py-3 text-sm">
          <summary class="cursor-pointer text-ink-2">Your answer</summary>
          <p class="mt-2 whitespace-pre-line text-ink">{written.answer_text}</p>
        </details>
      {/if}
      {#if written.status === 'pending'}
        <p class="rounded-xl border border-line bg-surface-2/60 p-4 text-sm text-ink-2" role="status">
          Grading against the marking scheme… This fills in automatically.
        </p>
      {:else if written.status === 'failed'}
        <p class="rounded-xl border border-warn/30 bg-warn-soft p-4 text-sm text-warn" role="status">
          This answer could not be graded automatically. The model answer and its sources are below.
        </p>
        <div class="mt-3">
          <WrittenFeedback result={{ ...written, attempt_id: null, score: 0, points: [] }} />
        </div>
      {:else}
        {#if written.stage_scores?.length}
          <ul class="mb-3 flex flex-wrap gap-2" aria-label="Marks per stage">
            {#each written.stage_scores as stage (stage.stage)}
              <li class="rounded-lg border border-line px-2.5 py-1 font-mono text-xs text-ink-2">
                {STAGE_LABELS[stage.stage as Stage] ?? stage.stage}: {stage.score}/{stage.max_score}
              </li>
            {/each}
          </ul>
        {/if}
        <WrittenFeedback result={{ ...written, attempt_id: null, score: written.score ?? 0 }} />
      {/if}
    {/if}
  </div>
</li>
