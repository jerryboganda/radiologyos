<script lang="ts">
  import CitationList from '$lib/components/CitationList.svelte';
  import type { VivaTurn } from '$lib/types/viva';
  import { VERDICT_LABEL, VERDICT_TONE } from '$lib/viva';

  let { turn }: { turn: VivaTurn } = $props();
  let evaluation = $derived(turn.evaluation);
  const TONE: Record<string, string> = { matched: 'text-ok', partial: 'text-warn', missed: 'text-danger' };
</script>

{#if evaluation}
  <div class="flex flex-col gap-3 rounded-xl border border-line bg-surface-2/60 p-4 text-sm">
    <p class="flex flex-wrap items-center gap-2">
      <span class="rounded-full border px-2 py-0.5 font-mono text-[0.6875rem] tracking-wide uppercase {VERDICT_TONE[evaluation.verdict] ?? ''}">
        {VERDICT_LABEL[evaluation.verdict] ?? evaluation.verdict}
      </span>
      {#if evaluation.max_score !== undefined}
        <span class="font-mono text-xs text-ink-2">{evaluation.score} / {evaluation.max_score}</span>
      {/if}
      {#if evaluation.unsafe}<span class="font-mono text-xs text-danger">Unsafe statement</span>{/if}
      {#if evaluation.move}
        <span class="text-xs text-muted">Next: {evaluation.move === 'escalate' ? 'one level deeper' : 'a probe on the weak point'}</span>
      {/if}
    </p>
    {#if evaluation.feedback}<p class="leading-relaxed text-ink-2">{evaluation.feedback}</p>{/if}
    <ol class="flex flex-col divide-y divide-line" aria-label="Expected points">
      {#each evaluation.points as point, i (i)}
        <li class="py-2">
          <p class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="text-ink">{point.point}</span>
            <span class="font-mono text-xs {TONE[point.status] ?? 'text-muted'}">
              {point.awarded !== undefined ? `${point.awarded}/${point.marks} · ` : ''}{point.status}
            </span>
          </p>
          {#if point.justification}<p class="mt-0.5 text-ink-2">{point.justification}</p>{/if}
          <CitationList citations={point.citations} class="mt-1" />
        </li>
      {/each}
    </ol>
    {#if evaluation.model_answer}
      <div>
        <p class="label">Model answer</p>
        <p class="mt-1 leading-relaxed whitespace-pre-line text-ink-2">{evaluation.model_answer}</p>
      </div>
    {/if}
    {#if evaluation.teaching_point && !evaluation.model_answer}
      <div class="rounded-lg border-l-2 border-accent pl-3">
        <p class="label">Teaching point</p>
        <p class="mt-1 leading-relaxed text-ink">{evaluation.teaching_point.text}</p>
        <CitationList citations={evaluation.teaching_point.citations} class="mt-1" />
      </div>
    {/if}
  </div>
{:else if turn.expected.length}
  <div class="rounded-xl border border-line bg-surface-2/60 p-4 text-sm">
    <p class="label">What the examiner expected</p>
    <ul class="mt-1 flex flex-col gap-2">
      {#each turn.expected as point, i (i)}
        <li>
          <span class="text-ink-2">{point.point}</span>
          <CitationList citations={point.citations} class="mt-1" />
        </li>
      {/each}
    </ul>
  </div>
{/if}
