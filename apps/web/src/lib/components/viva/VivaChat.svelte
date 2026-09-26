<script lang="ts">
  import type { VivaSession } from '$lib/types/viva';
  import AnswerBox from './AnswerBox.svelte';
  import TurnResult from './TurnResult.svelte';

  let { session, draft = '' }: { session: VivaSession; draft?: string } = $props();
  let waiting = $derived(session.status === 'active' && session.work !== 'none');
  const MOVE: Record<string, string> = { open: 'Opening', escalate: 'Deeper', probe: 'Probe' };
</script>

<ol class="flex flex-col gap-5" aria-label="Viva transcript">
  {#each session.turns as turn (turn.turn_no)}
    <li class="flex flex-col gap-2">
      <div class="max-w-[46rem] rounded-2xl rounded-tl-sm border border-line bg-surface px-4 py-3">
        <p class="label">Examiner · Q{turn.turn_no} · {MOVE[turn.move] ?? turn.move} · level {turn.level}</p>
        <p class="mt-1 text-[0.9375rem] leading-relaxed text-ink">{turn.prompt}</p>
        {#if turn.hint}<p class="mt-1 text-sm text-muted italic">Hint: {turn.hint}</p>{/if}
      </div>
      {#if turn.answer_text}
        <div class="ml-auto max-w-[46rem] rounded-2xl rounded-tr-sm bg-accent-soft px-4 py-3">
          <p class="label">You</p>
          <p class="mt-1 text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink">{turn.answer_text}</p>
        </div>
      {/if}
      {#if turn.status === 'answered' && waiting}
        <p class="text-sm text-muted" role="status">
          <span class="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true"></span>
          The examiner is marking your answer against your sources…
        </p>
      {:else if turn.status === 'graded' || session.status === 'finished'}
        <details class="rounded-xl" open={session.status === 'finished' || turn.turn_no === session.turns.length - 1}>
          <summary class="cursor-pointer text-sm text-ink-2">Marking for Q{turn.turn_no}</summary>
          <div class="mt-2"><TurnResult {turn} /></div>
        </details>
      {/if}
    </li>
  {/each}
</ol>

{#if session.status === 'active' && session.current_turn !== null && !waiting}
  <div class="mt-5">
    <AnswerBox turnNo={session.current_turn} label="Your answer to Q{session.current_turn}" {draft} />
  </div>
{/if}
