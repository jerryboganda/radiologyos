<script lang="ts">
  import { onMount } from 'svelte';
  import '../app.css';
  import { page } from '$app/state';
  import { parseThemePref } from '$lib/theme';
  import { themeState, watchSystemTheme } from '$lib/theme.svelte';

  let { children } = $props();

  onMount(() => {
    if ('serviceWorker' in navigator) {
      void navigator.serviceWorker.register('/service-worker.js');
    }
    return watchSystemTheme(() => themeState.pref ?? parseThemePref(page.data.theme as string | undefined));
  });
</script>

<svelte:head>
  <title>radbrain</title>
</svelte:head>

{@render children()}
