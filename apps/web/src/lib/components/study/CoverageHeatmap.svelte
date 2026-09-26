<script lang="ts">
  import { cellLabel, cellStyle, pct } from '$lib/heatmap';
  import type { HeatmapRow } from '$lib/types/session';

  let { rows }: { rows: HeatmapRow[] } = $props();
  let view = $state<'grid' | 'table'>('grid');
  const LEGEND = [0, 0.25, 0.5, 0.75, 1];
  const BAND: Record<string, string> = { weak: 'text-danger', learning: 'text-warn', mastered: 'text-ok' };
</script>

<section aria-labelledby="heatmap-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="heatmap-heading" class="text-xl font-semibold text-ink">Coverage by system and topic</h2>
    <div class="flex gap-1" role="group" aria-label="Heatmap view">
      <button type="button" class="btn btn-ghost px-3 py-1 text-xs" aria-pressed={view === 'grid'} onclick={() => (view = 'grid')}>Heatmap</button>
      <button type="button" class="btn btn-ghost px-3 py-1 text-xs" aria-pressed={view === 'table'} onclick={() => (view = 'table')}>Table</button>
    </div>
  </div>
  <p class="mt-1 text-sm text-ink-2">Cells show the share of mapped passages you have studied (cards reviewed, questions answered, or read in a session). Rows carry the system’s mastery band.</p>

  {#if view === 'grid'}
    <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted" aria-hidden="true">
      <span class="h-4 w-6 rounded border border-line" style={cellStyle(null)}></span> no material
      {#each LEGEND as value (value)}
        <span class="ml-2 h-4 w-6 rounded border border-line" style={cellStyle(value)}></span> {pct(value)}
      {/each}
    </div>
    <ul class="mt-3 flex flex-col gap-2">
      {#each rows as row (row.code)}
        <li class="grid gap-2 sm:grid-cols-[12rem_minmax(0,1fr)]">
          <div class="text-sm">
            <span class="text-ink">{row.title}</span>
            <span class="block text-xs {BAND[row.band] ?? 'text-muted'}">{row.band} · mastery {pct(row.mastery)}</span>
          </div>
          <ul class="flex flex-wrap gap-1.5" aria-label="{row.title} topics">
            {#each row.cells as cell (cell.code + cell.title)}
              <li
                class="min-w-[6.5rem] rounded-md border border-line px-2 py-1 text-xs text-ink"
                style={cellStyle(cell.coverage)}
                title={cellLabel(row.title, cell)}
                aria-label={cellLabel(row.title, cell)}
              >
                <span class="block truncate">{cell.title}</span>
                <span class="font-mono font-semibold tabular-nums">{pct(cell.coverage)}</span>
              </li>
            {/each}
          </ul>
        </li>
      {/each}
    </ul>
  {:else}
    <div class="panel mt-3 overflow-x-auto">
      <table class="w-full min-w-[40rem] text-left text-sm">
        <caption class="sr-only">Coverage by system and topic</caption>
        <thead class="label border-b border-line">
          <tr>
            <th scope="col" class="px-4 py-3 font-normal">System</th>
            <th scope="col" class="px-4 py-3 font-normal">Topic</th>
            <th scope="col" class="px-4 py-3 font-normal">Coverage</th>
            <th scope="col" class="px-4 py-3 font-normal">Passages</th>
            <th scope="col" class="px-4 py-3 font-normal">Accuracy</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          {#each rows as row (row.code)}
            {#each row.cells as cell, i (cell.code + cell.title)}
              <tr>
                {#if i === 0}<th scope="rowgroup" rowspan={row.cells.length} class="px-4 py-2 align-top font-normal text-ink">{row.title}<span class="block text-xs text-muted">{row.band}</span></th>{/if}
                <td class="px-4 py-2 text-ink-2">{cell.title}</td>
                <td class="px-4 py-2 font-mono text-xs text-ink-2">{pct(cell.coverage)}</td>
                <td class="px-4 py-2 font-mono text-xs text-ink-2">{cell.studied}/{cell.material}</td>
                <td class="px-4 py-2 font-mono text-xs text-ink-2">{pct(cell.accuracy)}</td>
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
