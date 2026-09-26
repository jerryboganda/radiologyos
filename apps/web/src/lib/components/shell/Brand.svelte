<script lang="ts">
  let { compact = false }: { compact?: boolean } = $props();
</script>

<a href="/" class="group inline-flex items-center gap-2.5 text-ink no-underline" aria-label="radbrain — Today">
  <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" class="shrink-0">
    <rect x="1" y="1" width="30" height="30" rx="8" class="fill-ink" />
    <circle cx="16" cy="16" r="9.5" fill="none" stroke-width="1.5" class="stroke-canvas" opacity="0.55" />
    <circle cx="16" cy="16" r="5.5" fill="none" stroke-width="1.5" class="stroke-canvas" opacity="0.8" />
    <circle cx="19.5" cy="13" r="2.6" class="fill-accent" />
  </svg>
  {#if !compact}
    <span class="font-display text-[1.35rem] font-semibold tracking-tight">radbrain</span>
  {/if}
</a>
