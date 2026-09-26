<script lang="ts">
  import type { PageTable } from '$lib/types/library';

  let {
    tables,
    selected = null,
    onselect
  }: { tables: PageTable[]; selected?: number | null; onselect: (block: number) => void } = $props();
</script>

{#if tables.length === 0}
  <p class="px-1 py-6 text-center text-sm text-muted">No tables were found on this page.</p>
{:else}
  <ul class="flex flex-col gap-4">
    {#each tables as table (table.id)}
      <li class="rounded-xl border p-2 {selected === table.block_no ? 'border-accent' : 'border-line'}">
        <button type="button" class="label mb-1.5 hover:text-accent" onclick={() => onselect(table.block_no)}>
          Table · block #{table.block_no} · {table.n_rows} × {table.n_cols}
        </button>
        <div class="overflow-x-auto">
          <table class="w-full border-collapse text-left text-xs">
            {#if table.header && table.cells.length}
              <thead>
                <tr>{#each table.cells[0] as cell, c (c)}<th scope="col" class="border-b border-line-strong px-2 py-1 font-semibold text-ink">{cell}</th>{/each}</tr>
              </thead>
            {/if}
            <tbody>
              {#each table.header ? table.cells.slice(1) : table.cells as row, r (r)}
                <tr class="even:bg-surface-2/50">
                  {#each row as cell, c (c)}<td class="border-b border-line px-2 py-1 align-top text-ink-2">{cell}</td>{/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </li>
    {/each}
  </ul>
{/if}
