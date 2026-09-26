<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { page } from '$app/state';

  // Acknowledge embedding-budget alerts through the web server (never the API
  // directly). Works without JS as a plain form post that returns here.
  let {
    ids,
    label = 'Acknowledge',
    class: className = 'btn btn-ghost min-h-9 py-1.5'
  }: { ids: string[]; label?: string; class?: string } = $props();
  let busy = $state(false);
  let error = $state('');

  async function submit(event: SubmitEvent & { currentTarget: EventTarget & HTMLFormElement }) {
    event.preventDefault();
    const form = event.currentTarget;
    busy = true;
    error = '';
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { accept: 'application/json' } });
      if (response.ok) await invalidateAll();
      else {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        error = body?.detail ?? 'Could not acknowledge. Try again.';
      }
    } catch {
      error = 'Can’t reach radbrain right now. Try again.';
    } finally {
      busy = false;
    }
  }
</script>

<form method="POST" action="/settings/alerts/ack" onsubmit={submit} class="flex flex-col items-end gap-1">
  {#each ids as id (id)}<input type="hidden" name="id" value={id} />{/each}
  <input type="hidden" name="next" value={`${page.url.pathname}${page.url.search}`} />
  <button type="submit" class={className} disabled={busy}>{busy ? 'Acknowledging…' : label}</button>
  {#if error}<span class="max-w-60 text-right text-xs" role="alert">{error}</span>{/if}
</form>
