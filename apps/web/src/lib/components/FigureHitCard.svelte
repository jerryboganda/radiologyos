<script lang="ts">
  import { readerHref } from '$lib/citations';
  import type { FigureHit } from '$lib/types/library';
  import { mediaUrl } from '$lib/viewer';
  import FigureActions from './FigureActions.svelte';

  let { figure, actions = true }: { figure: FigureHit; actions?: boolean } = $props();
  let url = $derived(mediaUrl(figure.image_path));
</script>

<li class="overflow-hidden rounded-xl border border-line bg-surface">
  <a href={readerHref(figure.source_id, figure.page_no)} class="group block">
    <div class="flex aspect-[4/3] items-center justify-center bg-stage">
      {#if url}
        <img src={url} alt={figure.caption || figure.description.slice(0, 80)} loading="lazy" class="max-h-full max-w-full object-contain" />
      {:else}
        <span class="font-mono text-[0.625rem] tracking-widest text-neutral-500 uppercase">No crop</span>
      {/if}
    </div>
    <div class="p-3">
      <p class="flex flex-wrap gap-1.5 font-mono text-[0.625rem] text-muted uppercase">
        {#if figure.modality}<span>{figure.modality}</span>{/if}
        {#if figure.anatomy}<span>· {figure.anatomy}</span>{/if}
      </p>
      {#if figure.caption}<p class="mt-1 line-clamp-2 text-sm text-ink">{figure.caption}</p>{/if}
      {#if figure.description}
        <p class="mt-1.5 line-clamp-3 text-xs leading-relaxed text-ink-2">
          <span class="font-mono text-[0.625rem] tracking-wider text-info uppercase">AI description:</span>
          {figure.description}
        </p>
      {/if}
      <p class="mt-2 truncate font-mono text-[0.6875rem] text-accent group-hover:underline">
        {figure.source_title} · p.{figure.page_no}
      </p>
    </div>
  </a>
  {#if actions}<div class="px-3 pb-3"><FigureActions figureId={figure.figure_id} /></div>{/if}
</li>
