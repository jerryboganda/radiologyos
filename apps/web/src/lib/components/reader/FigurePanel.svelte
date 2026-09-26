<script lang="ts">
  import type { PageFigure } from '$lib/types/library';
  import { mediaUrl } from '$lib/viewer';

  let { figures, visionStatus }: { figures: PageFigure[]; visionStatus: string | null } = $props();
</script>

{#if figures.length === 0}
  <p class="px-1 py-6 text-center text-sm text-muted">
    {visionStatus === 'done'
      ? 'No figures were detected on this page.'
      : 'Figures appear here once the vision pass has parsed this page.'}
  </p>
{:else}
  <ul class="flex flex-col gap-4">
    {#each figures as figure (figure.id)}
      {@const url = mediaUrl(figure.image_path)}
      <li class="overflow-hidden rounded-xl border border-line bg-surface">
        {#if url}
          <a href={url} target="_blank" rel="noopener" class="block bg-stage" title="Open at original resolution">
            <img src={url} alt={figure.caption || `Figure ${figure.figure_no + 1}`} loading="lazy" class="mx-auto max-h-72 w-auto object-contain" />
          </a>
        {/if}
        <div class="p-3.5">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="label">Fig {figure.figure_no + 1}</span>
            {#if figure.modality}
              <span class="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.625rem] text-ink-2 uppercase">{figure.modality}</span>
            {/if}
            {#if figure.anatomy}
              <span class="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.625rem] text-ink-2 uppercase">{figure.anatomy}</span>
            {/if}
          </div>
          {#if figure.caption}
            <p class="mt-2 text-sm text-ink"><span class="text-muted">Caption (from page):</span> {figure.caption}</p>
          {/if}
          {#if figure.description}
            <div class="mt-3 rounded-lg border border-dashed border-info/40 bg-info-soft/50 p-3">
              <p class="label !text-info">AI description · verify against the image</p>
              <p class="mt-1 text-sm leading-relaxed text-ink-2">{figure.description}</p>
              {#if figure.findings?.length}
                <ul class="mt-2 list-disc pl-5 text-sm text-ink-2">
                  {#each figure.findings as finding, i (i)}<li>{finding}</li>{/each}
                </ul>
              {/if}
            </div>
          {/if}
        </div>
      </li>
    {/each}
  </ul>
{/if}
