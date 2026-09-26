<script lang="ts">
  import { goto } from '$app/navigation';
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';

  let { sourceId, pageNo, pageCount }: { sourceId: string; pageNo: number; pageCount: number } = $props();
  let jump = $state('');

  function go(target: number) {
    if (target < 1 || (pageCount && target > pageCount)) return;
    void goto(readerHref(sourceId, target), { noScroll: true, keepFocus: true });
  }

  function onKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'ArrowLeft' || e.key === '[') go(pageNo - 1);
    if (e.key === 'ArrowRight' || e.key === ']') go(pageNo + 1);
  }
</script>

<svelte:window onkeydown={onKey} />

<nav class="flex items-center gap-1.5" aria-label="Page navigation">
  <a
    href={pageNo > 1 ? readerHref(sourceId, pageNo - 1) : undefined}
    aria-disabled={pageNo <= 1}
    data-sveltekit-noscroll
    class="btn btn-ghost min-h-9 px-2.5 py-1.5 {pageNo <= 1 ? 'pointer-events-none opacity-40' : ''}"
    aria-label="Previous page"><Icon name="left" size={18} /></a
  >
  <form
    class="flex items-center gap-1.5 font-mono text-xs text-muted"
    onsubmit={(e) => {
      e.preventDefault();
      go(Number(jump));
      jump = '';
    }}
  >
    <label for="jump" class="sr-only">Go to page</label>
    <input
      id="jump"
      bind:value={jump}
      inputmode="numeric"
      pattern="[0-9]*"
      placeholder={String(pageNo)}
      class="field h-9 min-h-9 w-14 px-2 text-center font-mono text-xs"
    />
    <span>/ {pageCount || '?'}</span>
  </form>
  <a
    href={!pageCount || pageNo < pageCount ? readerHref(sourceId, pageNo + 1) : undefined}
    aria-disabled={!!pageCount && pageNo >= pageCount}
    data-sveltekit-noscroll
    class="btn btn-ghost min-h-9 px-2.5 py-1.5 {pageCount && pageNo >= pageCount ? 'pointer-events-none opacity-40' : ''}"
    aria-label="Next page"><Icon name="right" size={18} /></a
  >
</nav>
