<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';
  import { NOTE_MAX, pagesLabel } from '$lib/red-list';
  import type { FlaggedFact } from '$lib/types/red-list';
  import Highlighted from './red/Highlighted.svelte';

  // A fact flagged as contradicting standard teaching: keep it as the source
  // says or reject it, with a note (ADR 0038, ADR 0041). Re-deciding is allowed.
  let { fact, error = '', message = '' }: { fact: FlaggedFact; error?: string; message?: string } = $props();
  let busy = $state(false);
  let decided = $derived(fact.status !== 'flagged');
</script>

<li
  class="rounded-xl border border-l-4 p-4 [contain-intrinsic-size:auto_480px] [content-visibility:auto] sm:p-5 {decided
    ? 'border-line border-l-line-strong bg-surface-2'
    : 'border-warn/40 border-l-danger bg-warn-soft'}"
  aria-labelledby="fact-{fact.id}"
>
  <div class="flex min-w-0 items-start gap-3">
    <Icon name={decided ? 'check' : 'alert'} size={22} class="mt-0.5 hidden sm:block {decided ? 'text-muted' : 'text-danger'}" />
    <div class="min-w-0 flex-1">
      <p class="text-sm font-semibold text-ink">
        <span class="wrap-anywhere">{fact.file_name}</span> ·
        <a class="link" href={readerHref(fact.source_id, fact.page_from)}>{pagesLabel(fact.page_from, fact.page_to)}</a>
      </p>
      <h3 id="fact-{fact.id}" class="label mt-2 text-warn">Your source says</h3>
      <p class="mt-1 font-medium break-words text-ink">{fact.statement}</p>
      {#if fact.doubt}
        <p class="mt-2 text-sm break-words text-danger"><span class="font-semibold">Why it may be wrong:</span> {fact.doubt}</p>
      {/if}
      {#if decided}
        <p class="mt-2">
          <span class="inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold {fact.status === 'rejected' ? 'border-danger/50 bg-danger-soft text-danger' : 'border-ok/50 bg-ok-soft text-ok'}">
            {fact.status === 'rejected' ? 'You rejected this fact' : 'You kept it as your source says'}
          </span>
        </p>
        {#if fact.note}<p class="mt-2 text-sm break-words text-ink-2"><span class="font-semibold text-ink">Your note:</span> {fact.note}</p>{/if}
      {/if}
      <section class="mt-3 min-w-0 rounded-lg border border-line bg-surface p-3">
        <h4 class="label mb-2">{fact.section_heading || 'Where it comes from'}</h4>
        <div class="max-h-80 overflow-y-auto text-sm leading-relaxed text-ink">
          {#if fact.section_text}
            <Highlighted text={fact.section_text} spans={[fact.evidence_span]} />
          {:else}
            <p class="break-words italic">“{fact.evidence_span}”</p>
          {/if}
        </div>
      </section>
      <form
        method="POST"
        action="?/decideFact"
        class="mt-3"
        use:enhance={() => {
          busy = true;
          return async ({ update }) => {
            await update({ reset: false });
            busy = false;
          };
        }}
      >
        <input type="hidden" name="id" value={fact.id} />
        <label for="fact-note-{fact.id}" class="mb-1 block text-sm font-medium text-ink">Your note (optional)</label>
        <textarea id="fact-note-{fact.id}" name="note" rows="2" maxlength={NOTE_MAX} class="field text-sm" value={fact.note ?? ''} disabled={busy}></textarea>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <button class="btn btn-ghost min-h-10 bg-surface px-3 text-sm" name="decision" value="keep" disabled={busy}>Keep as my source says</button>
          <button class="btn btn-danger min-h-10 px-3 text-sm" name="decision" value="reject" disabled={busy}>Reject this fact</button>
          {#if error}<p class="text-sm font-medium text-danger" role="alert">{error}</p>{/if}
          {#if message && !error}<p class="text-sm font-medium text-ok" role="status">{message}</p>{/if}
        </div>
      </form>
    </div>
  </div>
</li>
