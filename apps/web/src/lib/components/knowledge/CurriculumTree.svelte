<script lang="ts">
  import type { CurriculumTreeNode } from '$lib/types/knowledge';

  let { systems }: { systems: CurriculumTreeNode[] } = $props();
  const EXAM_LABELS: Record<string, string> = {
    fcps2_theory: 'FCPS theory',
    fcps2_toacs: 'TOACS',
    imm: 'IMM',
    frcr_2a: 'FRCR 2A',
    frcr_2b: 'FRCR 2B'
  };
</script>

{#snippet tags(exams: string[])}
  <span class="flex flex-wrap gap-1">
    {#each exams as exam (exam)}
      <span class="rounded-full bg-surface-2 px-1.5 py-0.5 font-mono text-[0.625rem] tracking-wide text-muted uppercase">{EXAM_LABELS[exam] ?? exam}</span>
    {/each}
  </span>
{/snippet}

<ul class="flex flex-col gap-2">
  {#each systems as system (system.code)}
    <li class="panel">
      <details>
        <summary class="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span>
            <span class="font-medium text-ink">{system.title}</span>
            <span class="label ml-2">{system.code} · {system.children.length} topics</span>
          </span>
          {@render tags(system.exams)}
        </summary>
        <ul class="flex flex-col gap-3 border-t border-line px-4 py-3">
          {#each system.children as topic (topic.code)}
            <li>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="text-sm font-medium text-ink">{topic.title} <span class="label ml-1">{topic.code}</span></span>
                {#if topic.exams.join() !== system.exams.join()}{@render tags(topic.exams)}{/if}
              </div>
              {#if topic.children.length}
                <p class="mt-1 text-sm text-ink-2">{topic.children.map((s) => s.title).join(' · ')}</p>
              {/if}
            </li>
          {/each}
        </ul>
      </details>
    </li>
  {/each}
</ul>
