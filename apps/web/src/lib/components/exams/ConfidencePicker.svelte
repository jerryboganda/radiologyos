<script lang="ts">
  import Kbd from '$lib/components/Kbd.svelte';
  import { CONFIDENCE_LABELS } from '$lib/exam-review';

  let {
    level,
    disabled = false,
    onchange
  }: { level: number | undefined; disabled?: boolean; onchange: (level: number | null) => void } = $props();
  const LEVELS = [1, 2, 3] as const;
</script>

<div class="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3" role="group" aria-label="How confident are you? Optional">
  <span class="text-xs text-muted">Confidence (optional)</span>
  {#each LEVELS as n (n)}
    <button
      type="button"
      class="btn btn-ghost h-8 px-2.5 text-xs {level === n ? 'border-accent bg-accent-soft text-accent' : ''}"
      aria-pressed={level === n}
      aria-keyshortcuts={String(n)}
      {disabled}
      onclick={() => onchange(level === n ? null : n)}
    >
      {CONFIDENCE_LABELS[n]} <Kbd key={String(n)} class="ml-1" />
    </button>
  {/each}
</div>
