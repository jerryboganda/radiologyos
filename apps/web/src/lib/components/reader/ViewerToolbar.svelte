<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { zoomIn, zoomOut } from '$lib/viewer';

  let {
    effective,
    mode,
    showBlocks = $bindable(false),
    original,
    blocksToggle = true,
    onzoom
  }: {
    effective: number;
    mode: 'fit' | 'scale';
    showBlocks?: boolean;
    original: string;
    /** False for a lone figure, which has no text blocks to overlay. */
    blocksToggle?: boolean;
    onzoom: (next: number | 'fit') => void;
  } = $props();

  const tool =
    'inline-flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-lg px-2 text-neutral-300 hover:bg-white/10 hover:text-white';
</script>

<div class="flex flex-wrap items-center gap-1 border-b border-stage-line px-2 py-1.5">
  <button type="button" class={tool} aria-label="Zoom out" onclick={() => onzoom(zoomOut(effective))}>
    <Icon name="zoomOut" size={18} />
  </button>
  <span class="w-14 text-center font-mono text-xs text-overlay tabular-nums" aria-live="polite">
    {Math.round(effective * 100)}%
  </span>
  <button type="button" class={tool} aria-label="Zoom in" onclick={() => onzoom(zoomIn(effective))}>
    <Icon name="zoomIn" size={18} />
  </button>
  <span class="mx-1 h-5 w-px bg-stage-line" aria-hidden="true"></span>
  <button
    type="button"
    class="{tool} {mode === 'fit' ? 'bg-white/10 text-white' : ''}"
    aria-pressed={mode === 'fit'}
    onclick={() => onzoom('fit')}
  >
    <Icon name="fit" size={16} /><span class="font-mono text-[0.6875rem] tracking-wider">FIT</span>
  </button>
  <button
    type="button"
    class="{tool} {mode === 'scale' && Math.abs(effective - 1) < 0.001 ? 'bg-white/10 text-white' : ''}"
    title="Actual pixels: one image pixel per screen pixel"
    onclick={() => onzoom(1)}
  >
    <span class="font-mono text-[0.6875rem] tracking-wider">1:1</span>
  </button>
  {#if blocksToggle}
    <span class="mx-1 h-5 w-px bg-stage-line" aria-hidden="true"></span>
    <button
      type="button"
      class="{tool} {showBlocks ? 'bg-white/10 text-overlay' : ''}"
      aria-pressed={showBlocks}
      onclick={() => (showBlocks = !showBlocks)}
    >
      <Icon name="layers" size={16} /><span class="font-mono text-[0.6875rem] tracking-wider">BLOCKS</span>
    </button>
  {/if}
  <a href={original} target="_blank" rel="noopener" class="{tool} ml-auto" title="Open the original image in a new tab">
    <Icon name="external" size={16} /><span class="sr-only">Open original image</span>
  </a>
</div>
