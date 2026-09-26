<script lang="ts">
  import type { VivaSession } from '$lib/types/viva';
  import { STAGE_LABELS, STAGES, type Stage } from '$lib/viva';
  import AnswerBox from './AnswerBox.svelte';
  import TurnResult from './TurnResult.svelte';

  let { session, draft = '' }: { session: VivaSession; draft?: string } = $props();
  let byStage = $derived(new Map(session.turns.map((turn) => [turn.stage ?? '', turn])));
  let waiting = $derived(session.status === 'active' && session.work !== 'none');

  function stateOf(stage: Stage): string {
    const turn = byStage.get(stage);
    if (!turn) return 'upcoming';
    if (turn.status === 'graded') return `${turn.evaluation?.score ?? 0} / ${turn.evaluation?.max_score ?? 0}`;
    if (turn.status === 'answered') return 'marking';
    if (turn.status === 'skipped') return 'not answered';
    return 'now';
  }
</script>

<ol class="flex flex-col gap-4" aria-label="Station stages">
  {#each STAGES as stage, i (stage)}
    {@const turn = byStage.get(stage)}
    {@const current = turn && session.current_turn === turn.turn_no && !waiting}
    <li class="panel p-4 {current ? 'border-accent' : ''}" aria-current={current ? 'step' : undefined}>
      <p class="flex flex-wrap items-baseline justify-between gap-2">
        <span class="font-semibold text-ink">{i + 1}. {STAGE_LABELS[stage]}</span>
        <span class="font-mono text-xs text-muted">{stateOf(stage)}</span>
      </p>
      {#if turn}
        <p class="mt-1 text-sm text-ink-2">{turn.prompt}</p>
        {#if turn.answer_text}
          <p class="mt-2 rounded-lg bg-accent-soft px-3 py-2 text-sm whitespace-pre-line text-ink">{turn.answer_text}</p>
        {/if}
        {#if turn.status === 'answered' && waiting}
          <p class="mt-2 text-sm text-muted" role="status">Marking this stage against its cited rubric…</p>
        {:else if turn.status === 'graded' || turn.status === 'skipped'}
          <div class="mt-3"><TurnResult {turn} /></div>
        {/if}
        {#if current}
          <div class="mt-3"><AnswerBox turnNo={turn.turn_no} label="Your answer" {draft} /></div>
        {/if}
      {/if}
    </li>
  {/each}
</ol>
