<script lang="ts">
  import { enhance } from '$app/forms';
  import type { LoadProblem } from '$lib/api-state';
  import { downloadHref, exportStatusText, hasActiveExport } from '$lib/data-rights';
  import { formatBytes, formatDate } from '$lib/format';
  import { pollWhile } from '$lib/poll.svelte';
  import type { DataJob } from '$lib/types/data-rights';
  import LoadIssue from '../LoadIssue.svelte';

  let { exports, problem }: { exports: DataJob[]; problem: LoadProblem | null } = $props();
  let busy = $state(false);
  let active = $derived(hasActiveExport(exports));

  pollWhile(() => active, 'app:exports', 4000, 15_000);
</script>

<p class="mt-1 mb-4 text-sm text-ink-2">
  One ZIP with every row stored for your account (as JSON, embeddings included), your cards and claims as cited Markdown, and your
  original uploads. Download links expire after 7 days.
</p>
<form
  method="POST"
  action="?/export"
  use:enhance={() => {
    busy = true;
    return async ({ update }) => {
      await update({ reset: false });
      busy = false;
    };
  }}
>
  <button class="btn btn-primary" type="submit" disabled={busy || active}>{active ? 'Export in progress…' : 'Export my data'}</button>
</form>

{#if problem}
  <div class="mt-4"><LoadIssue compact {problem} title="Exports are unreachable" icon="file" /></div>
{:else if exports.length}
  <ul class="mt-4 divide-y divide-line rounded-xl border border-line" aria-label="Your exports">
    {#each exports as job (job.id)}
      {@const href = downloadHref(job)}
      <li class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div class="min-w-0">
          <p class="text-sm font-medium text-ink">Export of {formatDate(job.created_at)}</p>
          <p class="label mt-0.5">
            {exportStatusText(job)}{job.byte_size ? ` · ${formatBytes(job.byte_size)}` : ''}{job.expires_at && job.status === 'succeeded'
              ? ` · expires ${formatDate(job.expires_at)}`
              : ''}
          </p>
        </div>
        {#if href && exportStatusText(job) === 'Ready to download'}
          <a class="btn btn-ghost min-h-9 py-1.5" {href} download data-sveltekit-reload>Download ZIP</a>
        {/if}
      </li>
    {/each}
  </ul>
{/if}
