<script lang="ts">
  let { status }: { status: string } = $props();

  const TONES: Record<string, string> = {
    ready: 'bg-ok-soft text-ok',
    succeeded: 'bg-ok-soft text-ok',
    approved: 'bg-ok-soft text-ok',
    failed: 'bg-danger-soft text-danger',
    rejected: 'bg-danger-soft text-danger',
    processing: 'bg-warn-soft text-warn',
    running: 'bg-warn-soft text-warn',
    in_progress: 'bg-warn-soft text-warn',
    proposed: 'bg-info-soft text-info',
    open: 'bg-info-soft text-info',
    active: 'bg-warn-soft text-warn',
    submitted: 'bg-ok-soft text-ok',
    resolved: 'bg-ok-soft text-ok',
    pending: 'bg-info-soft text-info'
  };
  let tone = $derived(TONES[status] ?? 'bg-surface-2 text-muted');
</script>

<span class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[0.6875rem] tracking-wide uppercase {tone}">
  {#if status === 'processing' || status === 'running'}
    <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-current"></span>
  {/if}
  {status.replace(/_/g, ' ')}
</span>
