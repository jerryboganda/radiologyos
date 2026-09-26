<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import type { DueCard, Rating } from '$lib/types/study';

  let { cards, total }: { cards: DueCard[]; total: number } = $props();
  let revealed = $state(false);
  let sending = $state(false);
  let card = $derived(cards[0] ?? null);

  const BUTTONS: { rating: Rating; label: string; hint: string; tone: string }[] = [
    { rating: 'again', label: 'Again', hint: '<1 d', tone: 'border-danger/40 text-danger hover:bg-danger-soft' },
    { rating: 'hard', label: 'Hard', hint: 'sooner', tone: 'border-warn/40 text-warn hover:bg-warn-soft' },
    { rating: 'good', label: 'Good', hint: 'on time', tone: 'border-ok/40 text-ok hover:bg-ok-soft' },
    { rating: 'easy', label: 'Easy', hint: 'later', tone: 'border-info/40 text-info hover:bg-info-soft' }
  ];

  $effect(() => {
    void card?.id;
    revealed = false;
  });
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="review-heading">
  <div class="flex items-baseline justify-between gap-3">
    <h2 id="review-heading" class="text-xl font-semibold text-ink">Review</h2>
    <p class="label">{total} due</p>
  </div>
  {#if !card}
    <p class="mt-6 text-center text-sm text-muted">All caught up. New cards arrive as your sources are processed.</p>
  {:else}
    <div class="mt-4 rounded-xl border border-line bg-surface-2/50 p-5">
      {#if card.topic}<p class="label mb-2">{card.topic}</p>{/if}
      <p class="font-display text-lg leading-snug text-ink">{card.front}</p>
      {#if revealed}
        <hr class="my-4 border-line" />
        <p class="text-[0.9375rem] leading-relaxed text-ink-2">{card.back}</p>
        <div class="mt-3 flex flex-wrap gap-1.5">
          {#each card.citations as citation, i (i)}<CitationChip {citation} />{/each}
        </div>
      {/if}
    </div>
    {#if !revealed}
      <button type="button" class="btn btn-primary mt-4 w-full" onclick={() => (revealed = true)}>Show answer</button>
    {:else}
      <form
        method="POST"
        action="?/review"
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
          <button type="submit" name="rating" value={b.rating} disabled={sending} class="btn flex-col gap-0 border bg-surface px-1 py-2 {b.tone}">
            <span>{b.label}</span><span class="font-mono text-[0.625rem] font-normal opacity-80">{b.hint}</span>
          </button>
        {/each}
      </form>
    {/if}
  {/if}
</section>
