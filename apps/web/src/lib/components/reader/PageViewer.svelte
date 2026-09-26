<script lang="ts">
  import { bboxCenter, bboxToStyle } from '$lib/bbox';
  import type { PageBlock, PageFigure } from '$lib/types/library';
  import { cssWidth, fitScale, zoomIn, zoomOut } from '$lib/viewer';
  import ViewerToolbar from './ViewerToolbar.svelte';

  let {
    src,
    alt,
    corner,
    blocks,
    figures,
    selected,
    showBlocks = $bindable(false),
    blocksToggle = true,
    onselect
  }: {
    src: string;
    alt: string;
    corner: string;
    blocks: PageBlock[];
    figures: PageFigure[];
    selected: number | null;
    showBlocks?: boolean;
    /** False for a lone figure: hides the block overlay toggle and its B shortcut. */
    blocksToggle?: boolean;
    onselect: (block: number) => void;
  } = $props();

  let stage: HTMLDivElement | undefined = $state();
  let frame: HTMLDivElement | undefined = $state();
  let stageWidth = $state(0);
  let natural = $state({ w: 0, h: 0 });
  let mode = $state<'fit' | 'scale'>('fit');
  let scale = $state(1);
  let dpr = $state(1);
  let loaded = $state(false);
  let failed = $state(false);
  let drag: { x: number; y: number; left: number; top: number; moved: boolean } | null = null;
  let wasDrag = false;

  let fit = $derived(fitScale(stageWidth - 32, natural.w, dpr));
  let effective = $derived(mode === 'fit' ? fit : scale);
  let frameStyle = $derived(mode === 'fit' || !natural.w ? 'width:100%' : `width:${cssWidth(natural.w, scale, dpr)}px`);

  $effect(() => {
    dpr = window.devicePixelRatio || 1;
  });

  $effect(() => {
    void src;
    loaded = false;
    failed = false;
  });

  $effect(() => {
    void selected;
    void effective;
    if (loaded) requestAnimationFrame(centerSelected);
  });

  $effect(() => {
    if (!stage) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setScale(e.deltaY < 0 ? zoomIn(effective) : zoomOut(effective));
    };
    stage.addEventListener('wheel', onWheel, { passive: false });
    return () => stage?.removeEventListener('wheel', onWheel);
  });

  function setScale(next: number | 'fit') {
    if (next === 'fit') mode = 'fit';
    else {
      mode = 'scale';
      scale = next;
    }
  }

  function onLoad(event: Event) {
    const img = event.currentTarget as HTMLImageElement;
    natural = { w: img.naturalWidth, h: img.naturalHeight };
    loaded = true;
  }

  function centerSelected() {
    if (!stage || !frame || selected == null) return;
    const block = blocks.find((b) => b.block_no === selected);
    const c = block ? bboxCenter(block.bbox, frame.clientWidth, frame.clientHeight) : null;
    if (!c) return;
    const left = frame.offsetLeft + c.x - stage.clientWidth / 2;
    const top = frame.offsetTop + c.y - stage.clientHeight / 2;
    stage.scrollTo({ left, top, behavior: 'smooth' });
  }

  function onPointerDown(e: PointerEvent) {
    wasDrag = false;
    if (e.pointerType !== 'mouse' || e.button !== 0 || !stage) return;
    drag = { x: e.clientX, y: e.clientY, left: stage.scrollLeft, top: stage.scrollTop, moved: false };
  }

  function onPointerMove(e: PointerEvent) {
    if (!drag || !stage) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    stage.scrollLeft = drag.left - dx;
    stage.scrollTop = drag.top - dy;
  }

  function onPointerUp() {
    wasDrag = drag?.moved ?? false;
    drag = null;
  }

  function onKey(e: KeyboardEvent) {
    const actions: Record<string, () => void> = {
      '+': () => setScale(zoomIn(effective)),
      '=': () => setScale(zoomIn(effective)),
      '-': () => setScale(zoomOut(effective)),
      '0': () => setScale('fit'),
      '1': () => setScale(1),
      b: () => {
        if (blocksToggle) showBlocks = !showBlocks;
      }
    };
    const run = actions[e.key];
    if (run) {
      e.preventDefault();
      run();
    }
  }
</script>

<div class="overflow-hidden rounded-2xl border border-stage-line bg-stage text-neutral-200">
  <ViewerToolbar
    {effective}
    {mode}
    bind:showBlocks
    {blocksToggle}
    original={src}
    onzoom={setScale}
  />
  <!-- A focusable, scrollable image region with keyboard zoom shortcuts. -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
  <div
    bind:this={stage}
    bind:clientWidth={stageWidth}
    class="relative h-[68dvh] overflow-auto p-4 select-none lg:h-[calc(100dvh-13rem)]
      {mode === 'scale' ? 'cursor-grab active:cursor-grabbing' : ''}"
    tabindex="0"
    role="region"
    aria-label={blocksToggle
      ? 'Page image. Plus and minus zoom, 0 fits, 1 shows actual pixels, B toggles blocks.'
      : `${alt}. Plus and minus zoom, 0 fits, 1 shows actual pixels.`}
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    onpointerleave={onPointerUp}
    onkeydown={onKey}
  >
    <div bind:this={frame} class="relative mx-auto" style={frameStyle}>
      <img {src} {alt} class="block h-auto w-full" draggable="false" onload={onLoad} onerror={() => (failed = true)} />
      {#if loaded}
        <div class="absolute inset-0">
          {#if showBlocks}
            {#each figures as figure (figure.id)}
              {@const style = bboxToStyle(figure.bbox)}
              {#if style}
                <div class="pointer-events-none absolute border border-dashed border-sky-300/80" {style}></div>
              {/if}
            {/each}
          {/if}
          {#each blocks as block (block.block_no)}
            {@const style = bboxToStyle(block.bbox)}
            {@const active = block.block_no === selected}
            {#if style && (showBlocks || active)}
              <button
                type="button"
                class="absolute rounded-[2px] transition-colors
                  {active
                  ? 'bg-overlay/15 shadow-[0_0_0_9999px_rgba(0,0,0,0.38)] outline-2 outline-overlay'
                  : 'bg-overlay/5 outline-1 outline-overlay/45 hover:bg-overlay/15'}"
                {style}
                aria-label="Block {block.block_no}: {block.kind}"
                aria-pressed={active}
                onclick={() => {
                  if (!wasDrag) onselect(block.block_no);
                }}
              ></button>
            {/if}
          {/each}
        </div>
      {/if}
      {#if failed}
        <p class="py-24 text-center font-mono text-xs text-neutral-400">Page image unavailable.</p>
      {/if}
    </div>
    <span class="pointer-events-none sticky bottom-0 left-0 mt-2 block font-mono text-[0.6875rem] tracking-widest text-overlay/80 uppercase">
      {corner}
      {#if natural.w}· {natural.w}×{natural.h}px{/if}
    </span>
  </div>
</div>
