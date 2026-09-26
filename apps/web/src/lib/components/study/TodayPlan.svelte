<script lang="ts">
  import CitationChip from '$lib/components/CitationChip.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import type { TodayPlan } from '$lib/types/study';

  let { plan }: { plan: TodayPlan } = $props();
  let total = $derived(plan.blocks.reduce((sum, b) => sum + b.minutes, 0));
  let done = $derived(plan.blocks.filter((b) => b.done).reduce((sum, b) => sum + b.minutes, 0));
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="plan-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="plan-heading" class="text-xl font-semibold text-ink">Today’s plan</h2>
    <p class="label">{done} / {total} min{plan.phase ? ` · ${plan.phase}` : ''}</p>
  </div>
  <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
    <div class="h-full rounded-full bg-accent" style="width: {total ? (done / total) * 100 : 0}%"></div>
  </div>
  {#if plan.blocks.length === 0}
    <p class="mt-6 text-sm text-muted">Nothing scheduled today. Rest is part of the plan.</p>
  {:else}
    <ol class="mt-4 flex flex-col divide-y divide-line">
      {#each plan.blocks as block (block.id)}
        <li class="flex items-start gap-3 py-3">
          <span
            class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border
              {block.done ? 'border-ok bg-ok text-surface' : 'border-line-strong text-transparent'}"
            aria-hidden="true"><Icon name="check" size={14} /></span
          >
          <div class="min-w-0 flex-1">
            <p class="text-[0.9375rem] font-medium text-ink {block.done ? 'line-through opacity-60' : ''}">
              {#if block.href}<a class="hover:text-accent" href={block.href}>{block.title}</a>{:else}{block.title}{/if}
            </p>
            <p class="label mt-0.5">{block.kind.replace(/_/g, ' ')} · {block.minutes} min{block.done ? ' · done' : ''}</p>
            {#if block.citations?.length}
              <div class="mt-1.5 flex flex-wrap gap-1.5">
                {#each block.citations as citation, i (i)}<CitationChip {citation} />{/each}
              </div>
            {/if}
          </div>
        </li>
      {/each}
    </ol>
  {/if}
</section>
