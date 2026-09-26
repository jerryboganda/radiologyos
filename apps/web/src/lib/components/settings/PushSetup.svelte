<script lang="ts">
  import Notice from '$lib/components/Notice.svelte';
  import { base64UrlToBytes } from '$lib/push';

  let { vapidKey }: { vapidKey: string | null } = $props();

  type Status = 'checking' | 'unsupported' | 'needs-install' | 'blocked' | 'off' | 'on';
  let status = $state<Status>('checking');
  let message = $state<{ tone: 'ok' | 'warn'; text: string } | null>(null);
  let busy = $state(false);

  $effect(() => {
    void refresh();
  });

  async function refresh() {
    const standalone = matchMedia('(display-mode: standalone)').matches;
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      status = ios && !standalone ? 'needs-install' : 'unsupported';
      return;
    }
    if (Notification.permission === 'denied') {
      status = 'blocked';
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    status = (await reg.pushManager.getSubscription()) ? 'on' : 'off';
  }

  async function call(method: 'POST' | 'DELETE', body: unknown, query = ''): Promise<string | null> {
    const response = await fetch(`/settings/push${query}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (response.ok) return null;
    const detail = ((await response.json().catch(() => null)) as { detail?: string } | null)?.detail;
    return detail ?? `Request failed (${response.status}).`;
  }

  async function enable() {
    if (!vapidKey) return;
    busy = true;
    message = null;
    try {
      if ((await Notification.requestPermission()) !== 'granted') return void (status = 'blocked');
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToBytes(vapidKey) });
      const error = await call('POST', sub.toJSON());
      if (error) {
        await sub.unsubscribe();
        message = { tone: 'warn', text: error };
      } else message = { tone: 'ok', text: 'Reminders will arrive on this device.' };
    } catch {
      message = { tone: 'warn', text: 'This browser refused the push subscription.' };
    } finally {
      busy = false;
      await refresh();
    }
  }

  async function disable() {
    busy = true;
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await call('DELETE', sub.toJSON());
      await sub.unsubscribe();
    }
    busy = false;
    message = { tone: 'ok', text: 'Push turned off for this device.' };
    await refresh();
  }

  async function test() {
    const error = await call('POST', {}, '?test');
    message = error ? { tone: 'warn', text: error } : { tone: 'ok', text: 'Test notification sent.' };
  }
</script>

<div class="flex flex-col gap-3">
  {#if status === 'needs-install'}
    <Notice tone="info">On iPhone/iPad, first add radbrain to your Home Screen (Share → Add to Home Screen), then open it from there to enable reminders.</Notice>
  {:else if status === 'unsupported'}
    <Notice tone="warn">This browser does not support push notifications.</Notice>
  {:else if status === 'blocked'}
    <Notice tone="warn">Notifications are blocked for this site. Allow them in your browser’s site settings, then reload.</Notice>
  {:else if !vapidKey}
    <Notice tone="info">Push delivery is coming online (the API has no <code class="font-mono">/v1/notifications/vapid-public-key</code> yet). Your reminder time is still saved when that service is live.</Notice>
  {/if}
  <div class="flex flex-wrap items-center gap-2">
    {#if status === 'on'}
      <span class="font-mono text-xs text-ok">● ON FOR THIS DEVICE</span>
      <button type="button" class="btn btn-ghost min-h-9 py-1.5" onclick={disable} disabled={busy}>Turn off</button>
      <button type="button" class="btn btn-ghost min-h-9 py-1.5" onclick={test} disabled={busy}>Send test</button>
    {:else}
      <button type="button" class="btn btn-primary" onclick={enable} disabled={busy || status !== 'off' || !vapidKey}>
        Enable push on this device
      </button>
    {/if}
  </div>
  {#if message}<Notice tone={message.tone}>{message.text}</Notice>{/if}
</div>
