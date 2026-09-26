<script lang="ts">
  import { stageLabel } from '$lib/tutor-stream';

  // Live progress for a streamed tutor answer: every stage reported so far,
  // the last one still running. Stages arrive over SSE (ADR 0013 v2).
  let { question, stages }: { question: string; stages: string[] } = $props();
</script>

{#if question}
  <p class="self-end rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[0.9375rem] text-ink">{question}</p>
{/if}
<div class="panel p-4 sm:p-5" aria-live="polite" aria-busy="true">
  <ol class="flex flex-col gap-2 text-sm">
    {#each stages as stage, i (i)}
      <li class="flex items-center gap-2 {i === stages.length - 1 ? 'text-ink' : 'text-muted'}">
        {#if i === stages.length - 1}
          <span class="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent" aria-hidden="true"></span>
        {:else}
          <span class="h-2 w-2 shrink-0 rounded-full bg-line" aria-hidden="true"></span>
        {/if}
        {stageLabel(stage)}
      </li>
    {/each}
  </ol>
  <p class="label mt-3 border-t border-line pt-3">Answers can take a minute; every sentence is checked before it is shown.</p>
</div>
