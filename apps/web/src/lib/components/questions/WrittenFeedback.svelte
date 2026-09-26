<script lang="ts">
  import CitationList from '$lib/components/CitationList.svelte';
  import type { AttemptOut } from '$lib/types/assessment';

  let { result }: { result: AttemptOut } = $props();
  const TONE: Record<string, string> = { matched: 'text-ok', partial: 'text-warn', missed: 'text-danger' };
</script>

<div class="flex flex-col gap-3 rounded-xl border border-line bg-surface-2/60 p-4">
  <p class="font-semibold text-ink">
    Scored {result.score} / {result.max_score} against the marking scheme
  </p>
  {#if result.feedback}<p class="text-[0.9375rem] leading-relaxed text-ink-2">{result.feedback}</p>{/if}
  {#if result.points?.length}
    <ol class="flex flex-col divide-y divide-line">
      {#each result.points as point, i (i)}
        <li class="py-2 text-sm">
          <p class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="text-ink">{point.point}</span>
            <span class="font-mono text-xs {TONE[point.status] ?? 'text-muted'}">{point.awarded}/{point.marks} · {point.status}</span>
          </p>
          {#if point.justification}<p class="mt-0.5 text-ink-2">{point.justification}</p>{/if}
          <CitationList citations={point.citations} class="mt-1" />
        </li>
      {/each}
    </ol>
  {/if}
  {#if result.model_answer}
    <div>
      <p class="label">Model answer</p>
      <p class="mt-1 text-sm leading-relaxed whitespace-pre-line text-ink-2">{result.model_answer}</p>
    </div>
  {/if}
  {#if result.key_findings?.length}
    <div>
      <p class="label">Key findings</p>
      <ul class="mt-1 list-disc pl-5 text-sm text-ink-2">{#each result.key_findings as finding, i (i)}<li>{finding}</li>{/each}</ul>
    </div>
  {/if}
  {#if result.explanation}<p class="text-sm leading-relaxed text-ink-2">{result.explanation}</p>{/if}
  <CitationList citations={result.citations} />
</div>
