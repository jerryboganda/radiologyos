<script lang="ts">
  import { percent } from '$lib/format';
  import { blockView, weightBasisLabel } from '$lib/study';
  import type { PlanOut } from '$lib/types/study';

  let { plan }: { plan: PlanOut } = $props();
  let blocks = $derived(plan.blocks.map((block) => ({ block, view: blockView(block) })));
  let priorities = $derived(plan.priorities.slice(0, 5));
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="plan-heading">
  <div class="flex flex-wrap items-baseline justify-between gap-3">
    <h2 id="plan-heading" class="text-xl font-semibold text-ink">Today’s plan</h2>
    <p class="label">{plan.minutes} min · {plan.phase.replace(/_/g, ' ')} phase</p>
  </div>
  {#if plan.rule}<p class="mt-1 text-sm text-ink-2">{plan.rule}</p>{/if}
  {#if blocks.length === 0}
    <p class="mt-6 text-sm text-muted">Nothing scheduled today. Rest is part of the plan.</p>
  {:else}
    <ol class="mt-4 flex flex-col divide-y divide-line">
      {#each blocks as { block, view }, i (i)}
        <li class="flex items-start gap-3 py-3">
          <span
            class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line-strong font-mono text-[0.6875rem] text-muted"
            aria-hidden="true">{i + 1}</span
          >
          <div class="min-w-0 flex-1">
            <p class="text-[0.9375rem] font-medium text-ink"><a class="hover:text-accent" href={view.href}>{view.title}</a></p>
            <p class="label mt-0.5">{block.kind} · {block.minutes} min{view.details.length ? ` · ${view.details.join(' · ')}` : ''}</p>
          </div>
        </li>
      {/each}
    </ol>
  {/if}
  {#if priorities.length}
    <h3 class="label mt-5 mb-2">Priority topics</h3>
    <ul class="flex flex-wrap gap-1.5">
      {#each priorities as item (item.code)}
        <li class="rounded-lg border border-line px-2.5 py-1 text-xs text-ink-2" title="Mastery {percent(item.mastery)}">
          <span class="font-mono text-muted">{item.code}</span> {item.title} · <span class="text-ink">{item.band}</span>
        </li>
      {/each}
    </ul>
  {/if}
  <p class="label mt-4 border-t border-line pt-3">Target retention {percent(plan.retention)} · {weightBasisLabel(plan.weight_policy, plan.weight_targets ?? [])}</p>
</section>
