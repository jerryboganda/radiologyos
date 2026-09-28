<script lang="ts">
  import { verdictText } from '$lib/red-list';
  import type { Verdict } from '$lib/types/red-list';

  let { verdict }: { verdict: Verdict | null } = $props();
  const TONES: Record<Verdict, string> = {
    correct: 'border-ok/50 bg-ok-soft text-ok',
    needs_fix: 'border-warn/50 bg-warn-soft text-warn',
    remove: 'border-danger/50 bg-danger-soft text-danger'
  };
</script>

<span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold {verdict ? TONES[verdict] : 'border-line bg-surface-2 text-muted'}">
  {verdict ? `Your verdict: ${verdictText(verdict)}` : 'Reviewed (no verdict)'}
</span>
