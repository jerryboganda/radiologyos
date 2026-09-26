<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationChip from '$lib/components/CitationChip.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatDate } from '$lib/format';
  import type { ConflictOut } from '$lib/types/knowledge';

  let {
    conflict,
    action = '?/resolve',
    trustAction = '?/trust'
  }: { conflict: ConflictOut; action?: string; trustAction?: string } = $props();
  let busy = $state(false);
  let sides = $derived([
    { label: 'A', side: conflict.claim_a },
    { label: 'B', side: conflict.claim_b }
  ]);
  const VERDICT = { conflict: 'True conflict', context: 'Both valid in different contexts', same: 'Same fact, worded differently' };
  const TRUST = { a: 'You trusted source A', b: 'You trusted source B', both: 'You kept both as valid in context' };
  const submit = () => {
    busy = true;
    return async ({ update }: { update: () => Promise<void> }) => {
      await update();
      busy = false;
    };
  };
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
  {#if conflict.ai_label}
    <div class="mt-3 rounded-xl border border-line bg-surface-2/40 p-3 text-sm">
      <p class="label mb-1">
        Model verdict · {VERDICT[conflict.ai_label]}{conflict.ai_confidence != null ? ` · ${Math.round(conflict.ai_confidence * 100)}% confident` : ''}
      </p>
      <p class="text-ink-2">{conflict.ai_rationale}</p>
      {#if conflict.ai_context}<p class="mt-1 text-xs text-muted">Context: {conflict.ai_context}</p>{/if}
      {#if conflict.ai_cites?.length}
        <p class="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          Relies on
          {#each sides.filter((s) => conflict.ai_cites?.includes(s.label)) as { label, side } (label)}
            <span class="font-mono">[{label}]</span><CitationChip citation={side.citation} />
          {/each}
        </p>
      {/if}
    </div>
  {/if}
  {#if conflict.status === 'resolved'}
    <p class="mt-3 text-sm text-ink-2">
      <span class="label">Resolved {formatDate(conflict.resolved_at)}{conflict.trust ? ` · ${TRUST[conflict.trust]}` : ''}:</span>
      {conflict.resolution}
    </p>
  {:else}
    <form method="POST" action={trustAction} class="mt-3 flex flex-wrap items-center gap-2" use:enhance={submit}>
      <input type="hidden" name="conflict_id" value={conflict.id} />
      <span class="label mr-1">Decide:</span>
      <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" name="trust" value="a" disabled={busy}>Trust source A</button>
      <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" name="trust" value="b" disabled={busy}>Trust source B</button>
      <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" name="trust" value="both" disabled={busy}>Both valid in context</button>
    </form>
    <details class="mt-3">
      <summary class="cursor-pointer text-sm text-accent">Resolve with a note instead</summary>
      <form method="POST" {action} class="mt-3 flex flex-col gap-3" use:enhance={submit}>
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
