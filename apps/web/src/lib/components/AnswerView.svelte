<script lang="ts">
  import type { TutorAnswer } from '$lib/types/tutor';
  import CitationChip from './CitationChip.svelte';

  let { answer }: { answer: TutorAnswer } = $props();
</script>

<article class="flex flex-col gap-3">
  <p class="self-end rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[0.9375rem] text-ink">{answer.question}</p>
  <div class="panel p-4 sm:p-5">
    {#if answer.segments.length === 0}
      <p class="text-sm text-ink-2">{answer.message ?? 'No grounded answer was found in your sources.'}</p>
    {/if}
    <div class="flex flex-col gap-3">
      {#each answer.segments as segment, i (i)}
        {@const uncited = segment.citations.length === 0 && segment.web_sources.length === 0}
        {#if segment.origin === 'web'}
          <div class="rounded-xl border border-web/30 bg-web-soft/60 p-3">
            <p class="label !text-web">From the web · not from your library</p>
            <p class="mt-1 text-[0.9375rem] leading-relaxed text-ink">{segment.text}</p>
            <div class="mt-2 flex flex-wrap gap-1.5">
              {#each segment.web_sources as web, j (j)}<CitationChip {web} />{/each}
              {#each segment.citations as citation, j (j)}<CitationChip {citation} />{/each}
            </div>
          </div>
        {:else if uncited || segment.origin === 'ungrounded'}
          <div class="rounded-xl border border-warn/30 bg-warn-soft/60 p-3">
            <p class="label !text-warn">Unverified · no citation</p>
            <p class="mt-1 text-[0.9375rem] leading-relaxed text-ink-2">{segment.text}</p>
          </div>
        {:else}
          <p class="text-[0.9375rem] leading-relaxed text-ink">
            {segment.text}
            {#each segment.citations as citation, j (j)}<span class="ml-1 inline-block"><CitationChip {citation} /></span>{/each}
          </p>
        {/if}
      {/each}
    </div>
    <p class="label mt-4 border-t border-line pt-3">Grounding: {answer.grounding}</p>
  </div>
</article>
