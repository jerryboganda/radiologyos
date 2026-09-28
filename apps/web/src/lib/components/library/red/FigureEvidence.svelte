<script lang="ts">
  import type { FigureDetail, RedItem } from '$lib/types/red-list';
  import PageThumb from './PageThumb.svelte';

  // The page image, then each figure on it: the crop, the AI's reading, and the
  // quote on the slide that the diagnosis was matched to (or its absence).
  let { item, page }: { item: RedItem; page: number | null } = $props();

  function facts(figure: FigureDetail): string {
    return [figure.modality, figure.anatomy].filter(Boolean).join(' · ');
  }
</script>

{#if page !== null}
  <PageThumb sourceId={item.source_id} {page} fileName={item.file_name} />
{/if}
{#if item.figures.length === 0}
  <p class="mt-3 text-sm text-muted italic">No figures are stored for this page any more.</p>
{:else}
  <ul class="mt-3 flex flex-col gap-3">
    {#each item.figures as figure (figure.id)}
      <li class="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-3 sm:flex-row">
        {#if figure.has_image}
          <a href="/media/figures/{figure.id}" target="_blank" rel="noopener" class="shrink-0 self-start">
            <img
              src="/media/figures/{figure.id}"
              alt="Figure {figure.figure_no ?? ''} on page {page ?? '?'} of {item.file_name}"
              loading="lazy"
              decoding="async"
              class="max-h-56 w-auto max-w-full rounded-sm border border-line object-contain sm:max-w-60"
            />
            <span class="sr-only">(opens full size in a new tab)</span>
          </a>
        {/if}
        <div class="min-w-0 flex-1 text-sm break-words">
          <p class="label">Figure {figure.figure_no ?? '—'}{facts(figure) ? ` · ${facts(figure)}` : ''}</p>
          {#if figure.caption}<p class="mt-1 text-ink-2 italic">{figure.caption}</p>{/if}
          <p class="mt-2 font-semibold text-ink">AI reading</p>
          <p class="text-ink">{figure.description || 'No reading.'}</p>
          {#if figure.findings.length}
            <ul class="mt-1 list-disc pl-5 text-ink-2">
              {#each figure.findings as finding, i (i)}<li>{finding}</li>{/each}
            </ul>
          {/if}
          <p class="mt-2 font-semibold text-ink">On your slide</p>
          {#if figure.source_quote}
            <p><mark class="rounded-sm bg-warn-soft px-0.5 text-ink ring-1 ring-warn/50">“{figure.source_quote}”</mark></p>
          {:else}
            <p class="font-medium text-danger">No matching quote found on your slide.</p>
          {/if}
          {#if figure.impression_origin}<p class="mt-1 text-xs text-muted">Diagnosis from: {figure.impression_origin}</p>{/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}
