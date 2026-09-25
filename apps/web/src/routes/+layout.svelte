<script lang="ts">
  import { onMount } from 'svelte';
  import '../app.css';
  import '../preview.css';

  let { children } = $props();

  onMount(() => {
    if ('serviceWorker' in navigator) {
      void navigator.serviceWorker.register('/service-worker.js');
    }
  });
</script>

<svelte:head>
  <title>radbrain</title>
</svelte:head>

<header class="site-header">
  <a class="brand" href="/" aria-label="radbrain home">radbrain</a>
  <nav aria-label="Primary navigation">
    <a href="/">Workspace</a>
    <a href="/api/health">Health</a>
    <a href="/preview">Preview</a>
  </nav>
</header>

<main>
  {@render children()}
</main>

<footer>
  <p>Private by default. Not a medical device.</p>
</footer>
