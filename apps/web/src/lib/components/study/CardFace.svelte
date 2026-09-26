<script lang="ts">
  import CitationChip from '$lib/components/CitationChip.svelte';
  import { CARD_TYPE_LABELS, cardType, clozeAnswer, clozeParts } from '$lib/cards';
  import type { CardOut } from '$lib/types/study';
  import { mediaUrl } from '$lib/viewer';

  let { card, revealed }: { card: CardOut; revealed: boolean } = $props();
  let kind = $derived(cardType(card));
  let image = $derived(kind === 'image' ? mediaUrl(card.figure_image_path) : null);
  let cloze = $derived(kind === 'cloze' ? clozeAnswer(card.back) : null);
  // Image cards open fitted; zoom shows actual pixels in a scrollable frame.
  let zoomed = $state(false);
  $effect(() => {
    void card.id;
    zoomed = false;
  });
</script>

<p class="label mb-2">
  <span class="font-mono">{card.curriculum_code}</span> · {card.topic}
  {#if kind !== 'basic'}<span class="ml-1 rounded border border-line px-1.5 py-px text-[0.625rem]">{CARD_TYPE_LABELS[kind]}</span>{/if}
</p>

{#if kind === 'image'}
  {#if image}
    <div class="relative overflow-hidden rounded-xl bg-stage">
      <div class={zoomed ? 'max-h-[70dvh] overflow-auto' : ''}>
        <button
          type="button"
          class="block w-full {zoomed ? 'cursor-zoom-out' : 'cursor-zoom-in'}"
          aria-pressed={zoomed}
          aria-label={zoomed ? 'Fit the image' : 'Zoom the image'}
          onclick={() => (zoomed = !zoomed)}
        >
          <img
            src={image}
            alt="Radiology figure for this card"
            class={zoomed ? 'max-w-none' : 'mx-auto max-h-[50dvh] w-auto'}
          />
        </button>
      </div>
      <span class="pointer-events-none absolute right-2 bottom-2 rounded bg-canvas/80 px-1.5 py-0.5 font-mono text-[0.625rem] text-ink-2">
        {zoomed ? 'Click to fit' : 'Click to zoom'}
      </span>
    </div>
  {:else}
    <p class="rounded-xl border border-line p-4 text-sm text-muted">The image for this card is unavailable.</p>
  {/if}
  <p class="mt-3 font-display text-lg leading-snug text-ink">{card.front}</p>
{:else if kind === 'cloze'}
  <p class="font-display text-lg leading-snug text-ink">
    {#each clozeParts(card.front) as part, i (i)}
      {#if part.blank}
        {#if revealed && cloze}
          <mark class="rounded bg-accent-soft px-1 text-accent">{cloze.answer}</mark>
        {:else}
          <span class="inline-block min-w-16 border-b-2 border-accent align-baseline" aria-label="blank"></span>
        {/if}
      {:else}{part.text}{/if}
    {/each}
  </p>
{:else}
  <p class="font-display text-lg leading-snug text-ink">{card.front}</p>
{/if}

{#if revealed}
  <hr class="my-4 border-line" />
  {#if cloze}
    <p class="text-[0.9375rem] font-semibold text-ink">{cloze.answer}</p>
    {#if cloze.rest}<p class="mt-2 text-sm leading-relaxed whitespace-pre-line text-ink-2">{cloze.rest}</p>{/if}
  {:else}
    <p class="text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink-2">{card.back}</p>
  {/if}
  <div class="mt-3"><CitationChip citation={card.citation} /></div>
{/if}
