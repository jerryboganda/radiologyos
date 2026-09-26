<script lang="ts">
  import { summarizeSteps, type StepState } from '$lib/pipeline';
  import type { StepStatus } from '$lib/types/library';

  let { steps, compact = false }: { steps: StepStatus[]; compact?: boolean } = $props();
  let views = $derived(summarizeSteps(steps));

  const BAR: Record<StepState, string> = {
    done: 'bg-ok',
    running: 'bg-warn animate-pulse',
    waiting: 'bg-line-strong',
    skipped: 'bg-line-strong opacity-50',
    failed: 'bg-danger'
  };
  const WORD: Record<StepState, string> = {
    done: 'done',
    running: 'running',
    waiting: 'waiting',
    skipped: 'skipped',
    failed: 'failed'
  };
</script>

<ol class="grid grid-cols-6 gap-1" aria-label="Processing steps">
  {#each views as view (view.step)}
    <li class="min-w-0" title="{view.label}: {WORD[view.state]}{view.detail ? ` (${view.detail})` : ''}">
      <span class="block h-1.5 rounded-full {BAR[view.state]}"></span>
      {#if !compact}
        <span class="mt-1 block truncate font-mono text-[0.625rem] tracking-wide text-muted uppercase">
          {view.label}
        </span>
      {/if}
      <span class="sr-only">{view.label}: {WORD[view.state]}{view.detail ? `, ${view.detail}` : ''}</span>
    </li>
  {/each}
</ol>
