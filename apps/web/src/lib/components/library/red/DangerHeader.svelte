<script lang="ts">
  import type { Snippet } from 'svelte';

  // The red danger header of the owner's review pages (ADR 0038).
  let {
    title,
    eyebrow = 'Danger · check before you trust',
    children
  }: { title: string; eyebrow?: string; children: Snippet } = $props();
</script>

<header class="mb-6 flex items-start gap-4 rounded-xl border border-l-4 border-danger/40 border-l-danger bg-danger-soft p-4 sm:p-5">
  <svg viewBox="0 0 24 24" class="h-10 w-10 shrink-0 text-danger sm:h-12 sm:w-12" aria-hidden="true">
    <path fill="currentColor" d="M10.3 3.9a2 2 0 0 1 3.4 0l8.5 14.1a2 2 0 0 1-1.7 3H3.5a2 2 0 0 1-1.7-3z" />
    <path stroke="var(--danger-soft)" stroke-width="2.2" stroke-linecap="round" d="M12 9v4.5M12 17.2h.01" />
  </svg>
  <div class="min-w-0">
    <p class="label text-danger">{eyebrow}</p>
    <h1 class="mt-1 text-3xl leading-tight font-semibold wrap-anywhere text-danger sm:text-4xl">{title}</h1>
    <div class="mt-2 max-w-2xl text-[0.9375rem] leading-relaxed text-ink">{@render children()}</div>
  </div>
</header>
