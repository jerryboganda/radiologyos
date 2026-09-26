<script lang="ts">
  import CitationChip from '$lib/components/CitationChip.svelte';
  import type { LearnStepView } from '$lib/types/session';
  import { mediaUrl } from '$lib/viewer';

  let { learn }: { learn: LearnStepView } = $props();
</script>

<div class="flex flex-col gap-4">
  {#if learn.chunks.length === 0 && learn.figures.length === 0}
    <p class="text-sm text-muted">The passages for this step are no longer in your library.</p>
  {/if}
  {#each learn.chunks as chunk (chunk.chunk_id)}
    <article class="rounded-xl border border-line bg-surface-2/50 p-4">
      {#if chunk.heading}<h4 class="font-display text-lg leading-snug text-ink">{chunk.heading}</h4>{/if}
      <p class="mt-2 text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink-2">{chunk.text}</p>
      <div class="mt-3"><CitationChip citation={chunk.citation} /></div>
    </article>
  {/each}
  {#if learn.figures.length}
    <h4 class="label">Figures</h4>
    <div class="grid gap-3 sm:grid-cols-2">
      {#each learn.figures as figure (figure.figure_id)}
        {@const image = mediaUrl(figure.image_path)}
        <figure class="overflow-hidden rounded-xl border border-line">
          {#if image}
            <div class="bg-stage">
              <img src={image} alt={figure.caption || figure.description || 'Figure from your library'} loading="lazy" class="mx-auto max-h-72 w-auto" />
            </div>
          {/if}
          <figcaption class="p-3 text-sm text-ink-2">
            {#if figure.modality}<span class="label mr-1">{figure.modality}</span>{/if}
            {figure.caption || figure.description}
            {#if figure.caption && figure.description}<span class="mt-1 block text-xs text-muted">{figure.description}</span>{/if}
            <span class="mt-2 block"><CitationChip citation={figure.citation} /></span>
          </figcaption>
        </figure>
      {/each}
    </div>
  {/if}
</div>
