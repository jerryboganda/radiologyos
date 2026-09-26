<script lang="ts">
  import { enhance } from '$app/forms';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { formatDate } from '$lib/format';
  import type { MergeOut } from '$lib/types/knowledge';

  let { merge }: { merge: MergeOut } = $props();
  let busy = $state(false);
  const pct = (value: number) => `${Math.round(value * 100)}%`;
</script>

<li class="panel p-5">
  <p class="flex flex-wrap items-center gap-2">
    <StatusBadge status={merge.status} />
    <span class="label">similarity {pct(merge.similarity)} · model says {merge.decision.replace(/_/g, ' ')} ({pct(merge.confidence)})</span>
  </p>
  <p class="mt-2 flex flex-wrap items-center gap-2 text-ink">
    <a class="link font-medium" href="/knowledge/{merge.concept_a}">{merge.a_name}</a>
    <span class="text-muted" aria-hidden="true">↔</span>
    <a class="link font-medium" href="/knowledge/{merge.concept_b}">{merge.b_name}</a>
  </p>
  <p class="mt-1.5 text-sm text-ink-2">{merge.rationale}</p>
  {#if merge.status === 'applied'}
    <p class="mt-1 text-xs text-muted">Merged {formatDate(merge.applied_at)} · {merge.moved_claims} claims moved</p>
  {/if}
  {#if merge.status === 'review' || merge.status === 'applied'}
    <form
      method="POST"
      action="?/merge"
      class="mt-3 flex flex-wrap gap-2"
      use:enhance={() => {
        busy = true;
        return async ({ update }) => {
          await update();
          busy = false;
        };
      }}
    >
      <input type="hidden" name="merge_id" value={merge.id} />
      {#if merge.status === 'review'}
        <button class="btn btn-primary min-h-9 px-3 py-1.5 text-sm" name="action" value="merge" disabled={busy}>Merge them</button>
        <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" name="action" value="distinct" disabled={busy}>Keep separate</button>
      {:else}
        <button class="btn btn-ghost min-h-9 px-3 py-1.5 text-sm" name="action" value="undo" disabled={busy}>Undo merge</button>
      {/if}
    </form>
  {/if}
</li>
