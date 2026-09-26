<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import Kbd from '$lib/components/Kbd.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import { reviewKey } from '$lib/shortcuts';
  import type { CardOut, Rating } from '$lib/types/study';

  let {
    cards,
    error = null,
    scheduledDays = null,
    embedded = false
  }: { cards: CardOut[]; error?: string | null; scheduledDays?: number | null; embedded?: boolean } = $props();
  let revealed = $state(false);
  let sending = $state(false);
  let rateForm = $state<HTMLFormElement | null>(null);
  let card = $derived(cards[0] ?? null);

  const BUTTONS: { rating: Rating; label: string; tone: string }[] = [
    { rating: 1, label: 'Again', tone: 'border-danger/40 text-danger hover:bg-danger-soft' },
    { rating: 2, label: 'Hard', tone: 'border-warn/40 text-warn hover:bg-warn-soft' },
    { rating: 3, label: 'Good', tone: 'border-ok/40 text-ok hover:bg-ok-soft' },
    { rating: 4, label: 'Easy', tone: 'border-info/40 text-info hover:bg-info-soft' }
  ];

  $effect(() => {
    void card?.id;
    revealed = false;
  });

  // Space reveals; 1–4 rate. Ignored while typing or with a modifier (lib/shortcuts).
  function onKey(event: KeyboardEvent) {
    if (!card || sending) return;
    const action = reviewKey(event, revealed);
    if (!action) return;
    event.preventDefault();
    if (action.kind === 'reveal') {
      revealed = true;
      return;
    }
    const button = rateForm?.querySelector<HTMLButtonElement>(`button[value="${action.rating}"]`);
    if (button) rateForm?.requestSubmit(button);
  }
</script>

<svelte:window onkeydown={onKey} />

<section id="review" class={embedded ? '' : 'panel p-5 sm:p-6'} aria-labelledby="review-heading">
  <div class="flex items-baseline justify-between gap-3">
    <h2 id="review-heading" class="text-xl font-semibold text-ink">Review</h2>
    <p class="label">{cards.length}{cards.length >= 50 ? '+' : ''} due</p>
  </div>
  {#if scheduledDays !== null}
    <p class="mt-1 text-xs text-muted">Last card scheduled in {scheduledDays} day{scheduledDays === 1 ? '' : 's'}.</p>
  {/if}
  {#if error}<div class="mt-3"><Notice tone="warn">{error}</Notice></div>{/if}
  {#if !card}
    <p class="mt-6 text-center text-sm text-muted">All caught up. Generate cards from a source to add more.</p>
  {:else}
    <div class="mt-4 rounded-xl border border-line bg-surface-2/50 p-5">
      <p class="label mb-2"><span class="font-mono">{card.curriculum_code}</span> · {card.topic}</p>
      <p class="font-display text-lg leading-snug text-ink">{card.front}</p>
      {#if revealed}
        <hr class="my-4 border-line" />
        <p class="text-[0.9375rem] leading-relaxed text-ink-2">{card.back}</p>
        <div class="mt-3"><CitationChip citation={card.citation} /></div>
      {/if}
    </div>
    {#if !revealed}
      <button type="button" class="btn btn-primary mt-4 w-full" aria-keyshortcuts="Space" onclick={() => (revealed = true)}>
        Show answer <Kbd key="Space" class="ml-1" />
      </button>
    {:else}
      <form
        method="POST"
        action="?/review"
        bind:this={rateForm}
        class="mt-4 grid grid-cols-4 gap-2"
        use:enhance={() => {
          sending = true;
          return async ({ update }) => {
            await update();
            sending = false;
          };
        }}
      >
        <input type="hidden" name="card_id" value={card.id} />
        {#each BUTTONS as b (b.rating)}
          <button
            type="submit"
            name="rating"
            value={b.rating}
            disabled={sending}
            aria-keyshortcuts={String(b.rating)}
            class="btn flex-col gap-0.5 border bg-surface px-1 py-2 {b.tone}"
          >
            {b.label} <Kbd key={String(b.rating)} />
          </button>
        {/each}
      </form>
    {/if}
  {/if}
</section>
