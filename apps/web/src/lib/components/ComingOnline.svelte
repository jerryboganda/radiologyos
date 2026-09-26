<script lang="ts">
  import Icon from './Icon.svelte';
  import type { IconName } from './icons';

  let {
    title,
    description,
    endpoints = [],
    icon = 'signal',
    compact = false
  }: {
    title: string;
    description: string;
    endpoints?: string[];
    icon?: IconName;
    compact?: boolean;
  } = $props();
</script>

<section
  class="panel relative overflow-hidden {compact ? 'p-5' : 'p-6 sm:p-8'}"
  aria-label="{title} — coming online"
>
  <div
    class="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full border border-dashed border-line-strong opacity-70"
    aria-hidden="true"
  ></div>
  <div class="relative flex items-start gap-4">
    <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-info-soft text-info">
      <Icon name={icon} />
    </span>
    <div class="min-w-0">
      <p class="label flex items-center gap-2">
        <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-info"></span>
        Coming online
      </p>
      <h2 class="mt-1 text-xl font-semibold text-ink">{title}</h2>
      <p class="mt-1.5 max-w-prose text-sm leading-relaxed text-ink-2">{description}</p>
      {#if endpoints.length}
        <p class="mt-3 flex flex-wrap gap-1.5">
          {#each endpoints as endpoint (endpoint)}
            <code class="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[0.6875rem] text-muted">{endpoint}</code>
          {/each}
        </p>
      {/if}
    </div>
  </div>
</section>
