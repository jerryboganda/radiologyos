<script lang="ts">
  import Notice from '$lib/components/Notice.svelte';
  import { pollWhile } from '$lib/poll.svelte';
  import type { ExamResult, QuestionPublic } from '$lib/types/assessment';
  import ExamResultItem from './ExamResultItem.svelte';

  let { result, questions }: { result: ExamResult; questions: QuestionPublic[] } = $props();
  let byId = $derived(new Map(questions.map((q) => [q.id, q])));
  let total = $derived(Math.round(result.max_score * 100) / 100);
  let pending = $derived(result.pending ?? 0);

  // The worker fills written items in one by one; re-read the exam until all are graded.
  pollWhile(() => pending > 0, 'app:exam', 4000, 15_000);

  const pct = (score: number | undefined, max: number | undefined, correct: number, count: number) =>
    max ? Math.round(((score ?? 0) / max) * 100) : count ? Math.round((correct / count) * 100) : 0;
</script>

<div class="flex flex-col gap-6">
  <section class="panel flex flex-wrap items-end gap-8 p-5 sm:p-6" aria-label="Score">
    <div>
      <p class="label">{pending ? 'Provisional score' : 'Score'}</p>
      <p class="font-display text-5xl font-semibold text-ink tabular-nums">{result.percent}<span class="text-xl text-muted">%</span></p>
    </div>
    <p class="text-sm text-ink-2">{result.score} of {total} marks · {result.answered} answered</p>
    {#if result.negative_marking?.enabled}
      <p class="text-sm text-ink-2">Negative marking: {result.raw_score} marks − {result.penalty} deducted for wrong answers</p>
    {/if}
  </section>
  {#if pending}
    <Notice tone="info">
      {pending} written answer{pending === 1 ? ' is' : 's are'} still being graded against the marking scheme. This page updates as each one finishes; pending items count as zero until then.
    </Notice>
  {/if}
  {#if result.failed}
    <Notice tone="warn">{result.failed} written answer{result.failed === 1 ? '' : 's'} could not be graded automatically and scored zero.</Notice>
  {/if}
  {#if result.timed_out}<Notice tone="info">Time ran out; the exam was graded from your last saved answers.</Notice>{/if}

  <section aria-labelledby="topic-heading">
    <h2 id="topic-heading" class="mb-3 text-xl font-semibold text-ink">By topic</h2>
    <div class="panel overflow-x-auto">
      <table class="w-full min-w-[28rem] text-left text-sm">
        <thead class="label border-b border-line">
          <tr><th class="px-4 py-3 font-normal">Topic</th><th class="px-4 py-3 font-normal">Marks</th><th class="px-4 py-3 font-normal">Answered</th><th class="px-4 py-3 font-normal">Score</th></tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each result.by_topic as topic (topic.topic)}
            <tr>
              <td class="px-4 py-3 text-ink">{topic.topic}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.score ?? topic.correct}/{topic.max_score ?? topic.total}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.answered}/{topic.total}</td>
              <td class="px-4 py-3 font-mono text-xs text-ink">{pct(topic.score, topic.max_score, topic.correct, topic.total)}%</td>
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
        <ExamResultItem {item} number={i + 1} question={byId.get(item.question_id)} />
      {/each}
    </ol>
  </section>
</div>
