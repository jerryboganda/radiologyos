<script lang="ts">
  import { isUuid, readerHref } from '$lib/citations';
  import type { TutorCitation } from '$lib/types/tutor';

  // A tutor figure citation: thumbnail via the authenticated /media proxy,
  // linking to the cited page in the reader.
  let { citation }: { citation: TutorCitation } = $props();
  let figureId = $derived(typeof citation.figure_id === 'string' && isUuid(citation.figure_id) ? citation.figure_id : null);
  let page = $derived(Number.isInteger(citation.page_from) && (citation.page_from ?? 0) >= 1 ? (citation.page_from as number) : 1);
  let title = $derived((citation.source_title ?? '').trim() || 'Untitled source');
  let href = $derived(
    typeof citation.source_id === 'string' && isUuid(citation.source_id) ? readerHref(citation.source_id, page) : null
  );
</script>

{#if figureId}
  <a
    href={href ?? `/media/figures/${figureId}`}
    class="inline-flex max-w-full items-center gap-2 rounded-md border border-line bg-surface-2 p-1 pr-2 align-middle font-mono text-[0.6875rem] text-ink-2 no-underline hover:border-accent hover:text-accent"
    title="Figure from {title}, page {page}"
  >
    <img
      src="/media/figures/{figureId}"
      alt="Cited figure from {title}, page {page}"
      loading="lazy"
      class="h-10 w-14 shrink-0 rounded bg-stage object-cover"
    />
    <span class="truncate">Figure · {title} · p.{page}</span>
  </a>
{/if}
