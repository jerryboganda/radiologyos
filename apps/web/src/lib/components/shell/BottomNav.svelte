<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';
  import { isActive, NAV } from '$lib/nav';

  let moreOpen = $state(false);
  const primary = NAV.filter((item) => item.primary);
  const secondary = NAV.filter((item) => !item.primary);
  let secondaryActive = $derived(secondary.some((item) => isActive(item.href, page.url.pathname)));

  $effect(() => {
    void page.url.pathname;
    moreOpen = false;
  });
</script>

{#if moreOpen}
  <button
    type="button"
    class="fixed inset-0 z-30 bg-black/40 lg:hidden"
    aria-label="Close menu"
    onclick={() => (moreOpen = false)}
  ></button>
  <div
    id="more-menu"
    class="fixed inset-x-3 z-40 rounded-2xl border border-line bg-surface p-2 shadow-xl lg:hidden"
    style="bottom: calc(4.75rem + env(safe-area-inset-bottom))"
  >
    {#each secondary as item (item.href)}
      <a
        href={item.href}
        class="flex items-center gap-3 rounded-xl px-4 py-3 text-base font-medium
          {isActive(item.href, page.url.pathname) ? 'bg-surface-2 text-ink' : 'text-ink-2'}"
      >
        <Icon name={item.icon} size={20} class="text-muted" />
        {item.label}
      </a>
    {/each}
  </div>
{/if}

<nav
  aria-label="Primary"
  class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 backdrop-blur lg:hidden"
  style="padding-bottom: env(safe-area-inset-bottom)"
>
  <ul class="mx-auto grid max-w-lg grid-cols-5">
    {#each primary as item (item.href)}
      {@const active = isActive(item.href, page.url.pathname)}
      <li>
        <a
          href={item.href}
          aria-current={active ? 'page' : undefined}
          class="flex h-16 flex-col items-center justify-center gap-1 text-[0.6875rem] font-medium
            {active ? 'text-accent' : 'text-muted'}"
        >
          <Icon name={item.icon} size={22} />
          {item.label}
        </a>
      </li>
    {/each}
    <li>
      <button
        type="button"
        class="flex h-16 w-full flex-col items-center justify-center gap-1 text-[0.6875rem] font-medium
          {moreOpen || secondaryActive ? 'text-accent' : 'text-muted'}"
        aria-expanded={moreOpen}
        aria-controls="more-menu"
        onclick={() => (moreOpen = !moreOpen)}
      >
        <Icon name="more" size={22} />
        More
      </button>
    </li>
  </ul>
</nav>
