<script lang="ts">
  import type { PageBlock } from '$lib/types/library';

  let {
    blocks,
    selected,
    onselect
  }: { blocks: PageBlock[]; selected: number | null; onselect: (block: number) => void } = $props();

  let list: HTMLOListElement | undefined = $state();

  $effect(() => {
    if (selected == null || !list) return;
    list.querySelector(`[data-block="${selected}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  });
</script>

{#if blocks.length === 0}
  <p class="px-1 py-6 text-center text-sm text-muted">No text was found on this page.</p>
{:else}
  <ol bind:this={list} class="flex flex-col gap-1">
    {#each blocks as block (block.block_no)}
      {@const active = block.block_no === selected}
      <li data-block={block.block_no}>
        <button
          type="button"
          class="w-full rounded-lg border-l-2 px-3 py-2 text-left transition-colors
            {active ? 'border-accent bg-accent-soft' : 'border-transparent hover:bg-surface-2'}"
          aria-current={active ? 'true' : undefined}
          onclick={() => onselect(block.block_no)}
        >
          <span class="label">{block.kind} · #{block.block_no}{block.origin === 'vision' ? ' · vision' : ''}</span>
          <span
            class="mt-0.5 block text-sm leading-relaxed text-ink
              {block.kind === 'heading' ? 'font-display text-base font-semibold' : ''}
              {active ? '' : 'line-clamp-4'}">{block.text}</span
          >
        </button>
      </li>
    {/each}
  </ol>
{/if}
