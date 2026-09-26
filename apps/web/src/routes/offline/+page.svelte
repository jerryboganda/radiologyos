<script lang="ts">
  import Brand from '$lib/components/shell/Brand.svelte';
</script>

<svelte:head>
  <title>Offline · radbrain</title>
</svelte:head>

<div class="flex min-h-dvh flex-col px-5 py-6 sm:px-8">
  <header><Brand /></header>
  <main class="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center py-16">
    <p class="label">No connection</p>
    <h1 class="mt-3 text-4xl font-semibold text-ink">You are offline.</h1>
    <p class="mt-3 text-lg leading-relaxed text-ink-2">
      Your library lives on the server and is never stored on this device, so it needs a connection. Everything will be
      where you left it.
    </p>
    <a class="btn btn-primary mt-8 self-start" href="/">Try again <span aria-hidden="true">→</span></a>
  </main>
</div>
