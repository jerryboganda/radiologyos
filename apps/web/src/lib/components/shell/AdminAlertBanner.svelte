<script lang="ts">
  import AlertAck from '$lib/components/AlertAck.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import { bannerMessage } from '$lib/admin-usage';
  import type { AdminBanner } from '$lib/types/admin';

  // Embedding-budget alert for admins, across the top of every app page.
  let { banner }: { banner: AdminBanner } = $props();
  let red = $derived(banner.level === 'red');

  // Red is solid (the budget is exhausted); amber is the soft warning tone.
  // The focus ring switches to the banner text colour so it stays visible.
  const TONE = {
    red: 'border-danger bg-danger text-surface [--focus:var(--surface)]',
    amber: 'border-warn/30 bg-warn-soft text-warn'
  };
  const ACK = {
    red: 'btn min-h-9 border-surface/60 py-1.5 text-surface hover:bg-surface/15',
    amber: 'btn min-h-9 border-warn/50 py-1.5 text-warn hover:bg-warn/10'
  };
</script>

<div role={red ? 'alert' : 'status'} class="border-b {TONE[banner.level]}">
  <div class="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6 lg:px-10">
    <div class="flex min-w-0 flex-1 basis-72 items-start gap-3">
      <Icon name="alert" size={20} class="mt-px" />
      <p class="text-sm leading-snug font-medium text-pretty">{bannerMessage(banner)}</p>
    </div>
    <div class="ms-auto flex shrink-0 items-start gap-1">
      <a href="/settings#ai-usage" class="inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-semibold underline decoration-1 underline-offset-3"
        >Settings</a
      >
      <AlertAck ids={banner.alertIds} class={ACK[banner.level]} />
    </div>
  </div>
</div>
