<script lang="ts">
  import CitationList from '$lib/components/CitationList.svelte';
  import { optionLetter } from '$lib/questions';
  import type { OptionExplanation } from '$lib/types/assessment';
  import type { LooseCitation } from '$lib/types/citation';

  let {
    correct,
    keyIndex,
    explanation,
    options = [],
    citations = []
  }: {
    correct: boolean | null | undefined;
    keyIndex: number | null | undefined;
    explanation: string;
    options?: OptionExplanation[];
    citations?: LooseCitation[];
  } = $props();
</script>

<div class="rounded-xl border border-line bg-surface-2/60 p-4">
  <p class="font-semibold {correct ? 'text-ok' : 'text-danger'}">
    {correct ? 'Correct.' : `Not quite — the answer is ${optionLetter(keyIndex)}.`}
  </p>
  <p class="mt-1.5 text-[0.9375rem] leading-relaxed text-ink-2">{explanation}</p>
  <CitationList {citations} class="mt-3" />
  {#if options.length}
    <details class="mt-3">
      <summary class="cursor-pointer text-sm text-ink-2">Why each option is right or wrong</summary>
      <ol class="mt-2 flex flex-col gap-2">
        {#each options as option, i (i)}
          <li class="text-sm">
            <p class="text-ink"><span class="font-mono text-xs text-muted">{optionLetter(i)}</span> {option.text}</p>
            <p class="text-ink-2">{option.explanation}</p>
            <CitationList citations={option.citations} class="mt-1" />
          </li>
        {/each}
      </ol>
    </details>
  {/if}
</div>
