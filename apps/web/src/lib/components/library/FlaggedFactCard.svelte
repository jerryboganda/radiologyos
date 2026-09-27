<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import { readerHref } from '$lib/citations';
  import { pagesLabel } from '$lib/red-list';
  import type { FlaggedFact } from '$lib/types/red-list';

  let { fact, error = '' }: { fact: FlaggedFact; error?: string } = $props();
  let busy = $state(false);
</script>

<li class="rounded-xl border border-l-4 border-warn/40 border-l-danger bg-warn-soft p-4 sm:p-5 {busy ? 'opacity-60' : ''}">
  <div class="flex items-start gap-3">
    <Icon name="alert" size={22} class="mt-0.5 text-danger" />
    <div class="min-w-0 flex-1">
      <p class="label text-warn">Your source says</p>
      <p class="mt-1 font-medium break-words text-ink">{fact.statement}</p>
      {#if fact.doubt}
        <p class="mt-2 text-sm text-danger"><span class="font-semibold">Why it may be wrong:</span> {fact.doubt}</p>
      {/if}
      <blockquote class="mt-3 border-l-2 border-warn/60 pl-3 text-sm break-words text-ink-2 italic">
        “{fact.evidence_span}”
      </blockquote>
      <p class="mt-2 text-sm">
        <a class="link" href={readerHref(fact.source_id, fact.page_from)}>
          {fact.source_title} · {pagesLabel(fact.page_from, fact.page_to)}
        </a>
      </p>
      {#if error}<p class="mt-2 text-sm font-medium text-danger" role="alert">{error}</p>{/if}
      <form
        method="POST"
        action="?/decideFact"
        class="mt-3 flex flex-wrap gap-2"
        use:enhance={() => {
          busy = true;
          return async ({ update }) => {
            await update();
            busy = false;
          };
        }}
      >
        <input type="hidden" name="id" value={fact.id} />
        <button class="btn btn-ghost min-h-9 bg-surface px-3 py-1.5 text-sm" name="decision" value="keep" disabled={busy}>
          Keep as my source says
        </button>
        <button class="btn btn-danger min-h-9 px-3 py-1.5 text-sm" name="decision" value="reject" disabled={busy}>
          Reject this fact
        </button>
      </form>
    </div>
  </div>
</li>
