<script lang="ts">
  import AdminAlertBanner from '$lib/components/shell/AdminAlertBanner.svelte';
  import BottomNav from '$lib/components/shell/BottomNav.svelte';
  import Brand from '$lib/components/shell/Brand.svelte';
  import Sidebar from '$lib/components/shell/Sidebar.svelte';
  import ThemeToggle from '$lib/components/shell/ThemeToggle.svelte';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: import('svelte').Snippet } = $props();
</script>

<a
  href="#main"
  class="sr-only z-50 rounded-lg bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
  >Skip to content</a
>

{#if data.user}
  <div class="flex min-h-dvh">
    <Sidebar user={data.user} />
    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-canvas/90 px-4 backdrop-blur lg:hidden"
        style="padding-top: env(safe-area-inset-top)"
      >
        <div class="flex h-14 items-center"><Brand /></div>
        <ThemeToggle />
      </header>
      {#if data.adminBanner}<AdminAlertBanner banner={data.adminBanner} />{/if}
      <main id="main" class="mx-auto w-full max-w-6xl flex-1 px-4 pt-6 pb-28 sm:px-6 lg:px-10 lg:pt-10 lg:pb-16">
        {@render children()}
      </main>
    </div>
  </div>
  <BottomNav />
{:else}
  <div class="flex min-h-dvh flex-col">
    <header class="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
      <Brand />
      <ThemeToggle />
    </header>
    <main id="main" class="mx-auto w-full max-w-6xl flex-1 px-5 sm:px-8">
      {@render children()}
    </main>
    <footer class="mx-auto w-full max-w-6xl px-5 py-8 text-xs text-muted sm:px-8">
      Private by default. Not a medical device.
    </footer>
  </div>
{/if}
