<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatDate } from '$lib/format';
  import type { ConflictOut } from '$lib/types/knowledge';

  let { conflict, action = '?/resolve' }: { conflict: ConflictOut; action?: string } = $props();
  let busy = $state(false);
  let sides = $derived([
    { label: 'A', side: conflict.claim_a },
    { label: 'B', side: conflict.claim_b }
  ]);
</script>

<li class="panel p-5">
  <p class="flex flex-wrap items-center gap-2">
    <a class="label hover:text-accent" href="/knowledge/{conflict.concept_id}">{conflict.concept_name}</a>
    <span class="label">· {conflict.kind.replace(/_/g, ' ')}</span>
    <StatusBadge status={conflict.status} />
  </p>
  <p class="mt-1 font-medium text-ink">{conflict.description}</p>
  <div class="mt-3 grid gap-3 sm:grid-cols-2">
    {#each sides as { label, side } (label)}
      <blockquote
        class="rounded-xl border-l-2 bg-surface-2/60 p-3 text-sm text-ink-2 {conflict.preferred_claim === side.claim_id ? 'border-ok' : 'border-warn'}"
      >
        <p class="label mb-1">Source {label}{conflict.preferred_claim === side.claim_id ? ' · preferred' : ''}</p>
        <p class="text-ink">{side.statement}</p>
        {#if side.evidence_span}<p class="mt-1 text-xs italic">“{side.evidence_span}”</p>{/if}
        <div class="mt-2"><CitationChip citation={side.citation} /></div>
      </blockquote>
    {/each}
  </div>
  {#if conflict.status === 'resolved'}
    <p class="mt-3 text-sm text-ink-2"><span class="label">Resolved {formatDate(conflict.resolved_at)}:</span> {conflict.resolution}</p>
  {:else}
    <details class="mt-3">
      <summary class="cursor-pointer text-sm text-accent">Resolve this conflict</summary>
      <form
        method="POST"
        {action}
        class="mt-3 flex flex-col gap-3"
        use:enhance={() => {
          busy = true;
          return async ({ update }) => {
            await update();
            busy = false;
          };
        }}
      >
        <input type="hidden" name="conflict_id" value={conflict.id} />
        <fieldset class="flex flex-wrap gap-2 text-sm text-ink-2">
          <legend class="label mb-1">Which source is right?</legend>
          <label class="flex items-center gap-1.5"><input type="radio" name="preferred_claim_id" value={conflict.claim_a.claim_id} /> A</label>
          <label class="flex items-center gap-1.5"><input type="radio" name="preferred_claim_id" value={conflict.claim_b.claim_id} /> B</label>
          <label class="flex items-center gap-1.5"><input type="radio" name="preferred_claim_id" value="" checked /> Both / context-dependent</label>
        </fieldset>
        <label class="block">
          <span class="label">Resolution note</span>
          <textarea name="resolution" rows="2" required maxlength="2000" class="field mt-1.5 resize-y"></textarea>
        </label>
        <div><button class="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save resolution'}</button></div>
      </form>
    </details>
  {/if}
</li>
