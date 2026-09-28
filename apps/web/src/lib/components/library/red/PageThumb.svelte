<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';

  // A lazy page thumbnail that opens the full-size page image, plus a reader link.
  let { sourceId, page, fileName }: { sourceId: string; page: number; fileName: string } = $props();
  let src = $derived(`/media/pages/${encodeURIComponent(sourceId)}/${page}`);
</script>

<div class="flex flex-col items-start gap-2">
  <a href={src} target="_blank" rel="noopener" class="block rounded-md border border-line bg-surface p-1 hover:border-line-strong">
    <img {src} alt="Page {page} of {fileName}" loading="lazy" decoding="async" class="h-44 w-auto max-w-full rounded-sm object-contain sm:h-52" />
    <span class="sr-only">(opens full size in a new tab)</span>
  </a>
  <a class="link inline-flex items-center gap-1 text-sm" href={readerHref(sourceId, page)}>
    Open in reader <Icon name="right" size={14} />
  </a>
</div>
