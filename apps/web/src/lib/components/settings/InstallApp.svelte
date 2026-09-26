<script lang="ts">
  import { installState, promptInstall } from '$lib/install.svelte';
  import Notice from '../Notice.svelte';

  let ios = $state(false);
  let declined = $state(false);

  $effect(() => {
    ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  });

  async function install() {
    declined = !(await promptInstall());
  }
</script>

<p class="mt-1 mb-4 text-sm text-ink-2">
  Install radbrain to open it from your home screen or dock in its own window. Your study data stays on the server; nothing
  private is stored for offline use.
</p>
{#if installState.installed}
  <p class="font-mono text-xs text-ok">● INSTALLED ON THIS DEVICE</p>
{:else if installState.prompt}
  <button type="button" class="btn btn-primary" onclick={install}>Install radbrain</button>
{:else if ios}
  <Notice tone="info">On iPhone or iPad, tap Share, then “Add to Home Screen”.</Notice>
{:else}
  <Notice tone="info">
    Use your browser’s menu (“Install app” or “Add to Home screen”). The button appears here when the browser offers installation.
  </Notice>
{/if}
{#if declined}<p class="mt-3 text-xs text-muted">Installation was dismissed. You can install later from the browser menu.</p>{/if}
