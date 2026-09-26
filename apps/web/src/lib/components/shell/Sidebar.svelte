<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';
  import { isActive, NAV } from '$lib/nav';
  import AccountCard from './AccountCard.svelte';
  import Brand from './Brand.svelte';
  import ThemeToggle from './ThemeToggle.svelte';

  type User = { subject: string; name: string; email?: string; tenantRole: string };
  let { user }: { user: User } = $props();
</script>

<aside
  class="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-surface/60 px-4 py-5 lg:flex"
>
  <div class="flex items-center justify-between px-2">
    <Brand />
    <ThemeToggle />
  </div>
  <nav aria-label="Primary" class="mt-8 flex flex-1 flex-col gap-0.5 overflow-y-auto">
    {#each NAV as item (item.href)}
      {@const active = isActive(item.href, page.url.pathname)}
      <a
        href={item.href}
        aria-current={active ? 'page' : undefined}
        class="relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[0.9375rem] font-medium
          {active ? 'bg-surface-2 text-ink' : 'text-ink-2 hover:bg-surface-2/70 hover:text-ink'}"
      >
        {#if active}<span class="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent"></span>{/if}
        <Icon name={item.icon} size={18} class={active ? 'text-accent' : 'text-muted'} />
        {item.label}
      </a>
    {/each}
  </nav>
  <AccountCard {user} />
  <p class="mt-3 px-2 text-[0.6875rem] leading-snug text-muted">Private by default. Not a medical device.</p>
</aside>
