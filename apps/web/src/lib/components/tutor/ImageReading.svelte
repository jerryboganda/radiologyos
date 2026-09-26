<script lang="ts">
  import { isUuid } from '$lib/citations';
  import type { ImageReading } from '$lib/types/tutor';

  // An image attached to a question, with the vision agent's reading. The
  // reading is AI output about the user's own image: it is labelled as such
  // and is never a citation (ADR 0025).
  let { imageId, reading = null }: { imageId: string | null | undefined; reading?: ImageReading | null } = $props();
  let src = $derived(typeof imageId === 'string' && isUuid(imageId) ? `/media/tutor-images/${imageId}` : null);
</script>

{#if src}
  <figure class="flex max-w-md flex-col gap-2 self-end">
    <a href={src} target="_blank" rel="noopener" class="block overflow-hidden rounded-xl border border-line bg-stage">
      <img {src} alt="Your attachment for this question" loading="lazy" class="max-h-64 w-full object-contain" />
    </a>
    {#if reading}
      <figcaption class="rounded-lg border border-dashed border-info/40 bg-info-soft/50 p-3 text-sm text-ink-2">
        <p class="label !text-info">AI reading of your image · not a verified finding, not a citation</p>
        <p class="mt-1">
          {[reading.modality, reading.anatomy].filter(Boolean).join(' · ')}{reading.impression
            ? ` — suggests ${reading.impression} (${reading.confidence} confidence)`
            : ''}
        </p>
        {#if reading.findings.length}
          <ul class="mt-1 list-disc pl-5">
            {#each reading.findings as finding, i (i)}<li>{finding}</li>{/each}
          </ul>
        {/if}
        {#if reading.differentials.length}<p class="mt-1">Differentials: {reading.differentials.join(', ')}</p>{/if}
      </figcaption>
    {/if}
  </figure>
{/if}
