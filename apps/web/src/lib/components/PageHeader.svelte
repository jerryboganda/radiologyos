<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    eyebrow,
    title,
    description,
    actions
  }: { eyebrow?: string; title: string; description?: string; actions?: Snippet } = $props();
</script>

<header class="mb-8 flex flex-wrap items-end justify-between gap-4">
  <div class="max-w-2xl">
    {#if eyebrow}<p class="label mb-2">{eyebrow}</p>{/if}
    <h1 class="text-3xl leading-tight font-semibold text-ink sm:text-4xl">{title}</h1>
    {#if description}<p class="mt-2 text-[0.9375rem] leading-relaxed text-ink-2">{description}</p>{/if}
  </div>
  {#if actions}<div class="flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</header>
