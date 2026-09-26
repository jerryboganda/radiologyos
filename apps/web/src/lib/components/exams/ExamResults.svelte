<script lang="ts">
  import Notice from '$lib/components/Notice.svelte';
  import SbaFeedback from '$lib/components/questions/SbaFeedback.svelte';
  import { optionLetter } from '$lib/questions';
  import type { ExamResult, QuestionPublic } from '$lib/types/assessment';

  let { result, questions }: { result: ExamResult; questions: QuestionPublic[] } = $props();
  let byId = $derived(new Map(questions.map((q) => [q.id, q])));
  let total = $derived(Math.round(result.max_score));
</script>

<div class="flex flex-col gap-6">
  <section class="panel flex flex-wrap items-end gap-8 p-5 sm:p-6" aria-label="Score">
    <div>
      <p class="label">Score</p>
      <p class="font-display text-5xl font-semibold text-ink tabular-nums">{result.percent}<span class="text-xl text-muted">%</span></p>
    </div>
    <p class="text-sm text-ink-2">{result.score} of {total} correct · {result.answered} answered</p>
  </section>
  {#if result.timed_out}<Notice tone="info">Time ran out; the exam was graded from your last saved answers.</Notice>{/if}

  <section aria-labelledby="topic-heading">
    <h2 id="topic-heading" class="mb-3 text-xl font-semibold text-ink">By topic</h2>
    <div class="panel overflow-x-auto">
      <table class="w-full min-w-[28rem] text-left text-sm">
        <thead class="label border-b border-line">
          <tr><th class="px-4 py-3 font-normal">Topic</th><th class="px-4 py-3 font-normal">Correct</th><th class="px-4 py-3 font-normal">Answered</th><th class="px-4 py-3 font-normal">Score</th></tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each result.by_topic as topic (topic.topic)}
            <tr>
              <td class="px-4 py-3 text-ink">{topic.topic}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.correct}/{topic.total}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.answered}/{topic.total}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink">{topic.total ? Math.round((topic.correct / topic.total) * 100) : 0}%</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section aria-labelledby="review-heading">
    <h2 id="review-heading" class="mb-3 text-xl font-semibold text-ink">Answers with cited keys</h2>
    <ol class="flex flex-col gap-4">
      {#each result.items as item, i (item.question_id)}
        {@const question = byId.get(item.question_id)}
        <li class="panel p-5">
          <p class="label">Q{i + 1}{item.topic ? ` · ${item.topic}` : ''} · your answer {optionLetter(item.selected_option)}</p>
          {#if question}<p class="mt-2 leading-snug whitespace-pre-line text-ink">{question.stem}</p>{/if}
          <div class="mt-3">
            <SbaFeedback
              correct={item.correct}
              keyIndex={item.key}
              explanation={item.explanation}
              options={item.option_explanations}
              citations={item.citations}
            />
          </div>
        </li>
      {/each}
    </ol>
  </section>
</div>
