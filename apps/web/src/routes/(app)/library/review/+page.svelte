<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import DangerHeader from '$lib/components/library/red/DangerHeader.svelte';
  import FileCard from '$lib/components/library/red/FileCard.svelte';
  import { openCount, summaryCount } from '$lib/red-list';
  import type { FileSummary } from '$lib/types/red-list';
  import type { PageData } from './$types';

  // The owner's red review list, one card per file (ADR 0038, ADR 0041).
  let { data }: { data: PageData } = $props();
  let filter = $state('');

  let total = $derived(summaryCount(data.files));
  let needle = $derived(filter.trim().toLowerCase());
  let shown = $derived(
    needle ? data.files.filter((f) => `${f.file_name} ${f.source_title}`.toLowerCase().includes(needle)) : data.files
  );
  let open = $derived(shown.filter((f) => openCount(f) > 0));
  let done = $derived(shown.filter((f) => openCount(f) === 0));

  function sum(key: keyof Omit<FileSummary, 'source_id' | 'source_title' | 'file_name' | 'reasons'>): number {
    return data.files.reduce((n, f) => n + f[key], 0);
  }
  let stats = $derived([
    { label: 'Pages open', n: sum('open_pages') },
    { label: 'Figures open', n: sum('open_figures') },
    { label: 'Note sections open', n: sum('open_notes') },
    { label: 'Facts open', n: sum('open_facts') }
  ]);
  let reviewed = $derived(sum('reviewed'));
</script>

<svelte:head><title>{total ? `(${total}) ` : ''}Needs your review · radbrain</title></svelte:head>

<p class="mb-4 text-sm">
  <a href="/library" class="label inline-flex items-center gap-1 hover:text-ink"><Icon name="left" size={12} /> Library</a>
</p>

<DangerHeader title="Needs your review">
  These parts of your library fell short of the quality check, or no model could read them. Open each file, compare the
  evidence with the original page, and give your verdict.
</DangerHeader>

{#if data.problem}
  <LoadIssue problem={data.problem} title="The review list is unreachable" icon="library" />
{:else}
  <section aria-labelledby="totals" class="mb-8">
    <h2 id="totals" class="sr-only">Totals</h2>
    <dl class="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {#each stats as stat (stat.label)}
        <div class="min-w-0 rounded-lg border px-3 py-2 {stat.n ? 'border-danger/40 bg-danger-soft' : 'border-line bg-surface'}">
          <dt class="label break-words">{stat.label}</dt>
          <dd class="font-mono text-2xl font-semibold {stat.n ? 'text-danger' : 'text-muted'}">{stat.n}</dd>
        </div>
      {/each}
      <div class="min-w-0 rounded-lg border border-ok/30 bg-ok-soft px-3 py-2">
        <dt class="label">Reviewed</dt>
        <dd class="font-mono text-2xl font-semibold text-ok">{reviewed}</dd>
      </div>
    </dl>
    <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <a class="btn btn-ghost min-h-11 self-start bg-surface px-4" href="/library/review/export.csv" download data-sveltekit-reload>
        <Icon name="file" size={16} /> Download everything (CSV)
      </a>
      {#if data.files.length > 6}
        <div class="min-w-0 sm:w-72">
          <label for="file-filter" class="mb-1 block text-sm font-medium text-ink">Find a file</label>
          <input id="file-filter" type="search" class="field text-sm" bind:value={filter} placeholder="File name or title" />
        </div>
      {/if}
    </div>
  </section>

  <section aria-labelledby="open-files" class="mb-10">
    <h2 id="open-files" class="mb-3 flex items-center gap-2 text-xl font-semibold text-ink">
      Files to review
      <span class="rounded-full px-2 py-0.5 font-mono text-xs {open.length ? 'bg-danger text-surface' : 'bg-surface-2 text-muted'}">{open.length}</span>
    </h2>
    {#if open.length === 0}
      <p class="flex items-center gap-2 text-sm text-ok">
        <Icon name="check" size={16} />
        {needle ? 'No open file matches.' : 'Nothing needs review right now.'}
      </p>
    {:else}
      <ul class="grid gap-3 lg:grid-cols-2">
        {#each open as file (file.source_id)}<FileCard {file} />{/each}
      </ul>
    {/if}
  </section>

  {#if done.length}
    <section aria-labelledby="done-files">
      <h2 id="done-files" class="mb-3 flex items-center gap-2 text-lg font-semibold text-ok">
        <Icon name="check" size={18} /> All reviewed <span class="font-mono text-xs">({done.length})</span>
      </h2>
      <ul class="flex flex-col gap-2">
        {#each done as file (file.source_id)}<FileCard {file} />{/each}
      </ul>
    </section>
  {/if}
{/if}
