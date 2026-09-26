<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  let { tone = 'info', children }: { tone?: 'info' | 'warn' | 'danger' | 'ok'; children: Snippet } = $props();
  const STYLES = {
    info: 'border-info/30 bg-info-soft text-info',
    warn: 'border-warn/30 bg-warn-soft text-warn',
    danger: 'border-danger/30 bg-danger-soft text-danger',
    ok: 'border-ok/30 bg-ok-soft text-ok'
  };
</script>

<div
  class="flex items-start gap-3 rounded-xl border px-4 py-3 text-sm {STYLES[tone]}"
  role={tone === 'danger' ? 'alert' : 'status'}
>
  <Icon name={tone === 'ok' ? 'check' : 'alert'} size={18} class="mt-0.5" />
  <div class="min-w-0 leading-relaxed">{@render children()}</div>
</div>
