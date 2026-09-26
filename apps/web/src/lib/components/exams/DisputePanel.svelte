<script lang="ts">
  import { enhance } from '$app/forms';
  import { disputeFor } from '$lib/exam-review';
  import type { WrittenResultItem } from '$lib/types/assessment';
  import type { DisputeOut } from '$lib/types/results';

  let { item, disputes }: { item: WrittenResultItem; disputes: DisputeOut[] } = $props();
  // Points that lost marks can be disputed once each; the owner/admin reviews them.
  let rows = $derived(
    (item.points ?? []).map((point, index) => ({ point, index, dispute: disputeFor(disputes, item.question_id, index) }))
  );
  let open = $derived(rows.filter((r) => r.dispute || r.point.awarded < r.point.marks));
  let busy = $state(false);
  const STATUS: Record<string, string> = {
    open: 'Dispute open — awaiting review',
    accepted: 'Dispute accepted',
    rejected: 'Dispute rejected'
  };
</script>

{#if open.length}
  <details class="mt-3 rounded-xl border border-line px-4 py-3 text-sm">
    <summary class="cursor-pointer text-ink-2">Dispute a mark</summary>
    <ul class="mt-2 flex flex-col gap-3">
      {#each open as row (row.index)}
        <li class="rounded-lg border border-line p-3">
          <p class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="text-ink">{row.point.point}</span>
            <span class="font-mono text-xs text-ink-2">{row.point.awarded}/{row.point.marks}</span>
          </p>
          {#if row.dispute}
            <p class="mt-1 text-xs text-muted" role="status">
              {STATUS[row.dispute.status] ?? row.dispute.status}{row.dispute.awarded_after !== null ? ` · now ${row.dispute.awarded_after}/${row.dispute.marks}` : ''}{row.dispute.resolution_note ? ` · ${row.dispute.resolution_note}` : ''}
            </p>
          {:else}
            <form
              method="POST"
              action="?/dispute"
              class="mt-2 flex flex-col gap-2"
              use:enhance={() => {
                busy = true;
                return async ({ update }) => {
                  await update();
                  busy = false;
                };
              }}
            >
              <input type="hidden" name="question_id" value={item.question_id} />
              <input type="hidden" name="point_index" value={row.index} />
              <label class="block">
                <span class="label">Why does your answer earn this point?</span>
                <textarea name="reason" required maxlength="2000" class="field mt-1 min-h-16 w-full"></textarea>
              </label>
              <button class="btn btn-ghost self-start" type="submit" disabled={busy}>Send dispute</button>
            </form>
          {/if}
        </li>
      {/each}
    </ul>
  </details>
{/if}
