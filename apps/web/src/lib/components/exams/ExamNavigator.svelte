<script lang="ts">
  import type { Answers } from '$lib/types/assessment';

  let {
    ids,
    answers,
    current,
    onselect
  }: { ids: string[]; answers: Answers; current: number; onselect: (index: number) => void } = $props();
</script>

<nav aria-label="Question navigator">
  <ol class="grid grid-cols-8 gap-1.5 sm:grid-cols-10 lg:grid-cols-5">
    {#each ids as id, i (id)}
      {@const answered = typeof answers[id] === 'number'}
      <li>
        <button
          type="button"
          onclick={() => onselect(i)}
          aria-current={i === current ? 'step' : undefined}
          aria-label="Question {i + 1}{answered ? ', answered' : ', not answered'}"
          class="flex h-9 w-full items-center justify-center rounded-lg border font-mono text-xs tabular-nums
            {i === current ? 'border-accent ring-2 ring-accent/40' : 'border-line'}
            {answered ? 'bg-accent-soft text-ink' : 'bg-surface text-muted'}"
        >
          {i + 1}
        </button>
      </li>
    {/each}
  </ol>
</nav>
