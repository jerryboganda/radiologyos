<script lang="ts">
  import { invalidate } from '$app/navigation';
  import { clockOffset, formatClock, remainingMs } from '$lib/exam-session';

  let { deadlineAt, serverTime }: { deadlineAt: string; serverTime: string } = $props();
  let offset = $derived(clockOffset(serverTime, Date.now()));
  let now = $state(Date.now());
  let left = $derived(remainingMs(deadlineAt, offset, now) ?? 0);
  let reloaded = false;

  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  // The server owns the clock: at zero, reload so it can finish the session.
  $effect(() => {
    if (left === 0 && !reloaded) {
      reloaded = true;
      void invalidate('app:viva');
    }
  });
</script>

<span
  class="rounded-lg border px-2.5 py-1 font-mono text-sm tabular-nums {left < 60_000 ? 'border-danger/40 text-danger' : 'border-line text-ink-2'}"
  role="timer"
  aria-label="Time left {formatClock(left)}"
>
  {formatClock(left)}
</span>
