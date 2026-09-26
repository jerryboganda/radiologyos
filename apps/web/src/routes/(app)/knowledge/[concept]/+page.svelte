<script lang="ts">
  import CitationChip from '$lib/components/CitationChip.svelte';
  import CitationList from '$lib/components/CitationList.svelte';
  import FigureHitCard from '$lib/components/FigureHitCard.svelte';
  import ConceptGraph from '$lib/components/knowledge/ConceptGraph.svelte';
  import ConceptNote from '$lib/components/knowledge/ConceptNote.svelte';
  import ConflictCard from '$lib/components/knowledge/ConflictCard.svelte';
  import DdxTree from '$lib/components/knowledge/DdxTree.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { ddxTree, footnotes } from '$lib/concept-note';
  import { percent } from '$lib/format';
  import { EXAM_TARGETS } from '$lib/types/study';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let c = $derived(data.concept);
  let claims = $derived([...c.claims].sort((a, b) => b.importance - a.importance));
  let body = $derived(data.note?.note?.body ?? null);
  let numbers = $derived(body ? footnotes(body, c.claims).numbers : new Map<string, number>());
  let branches = $derived(ddxTree(body, c.edges));
</script>

<svelte:head><title>{c.name} · Knowledge · radbrain</title></svelte:head>

{#snippet feedback(section: string)}
  {#if form?.section === section}
    <div class="mb-3">
      {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
          >{form.message}</Notice
        >{:else}<Notice tone="ok">Saved.</Notice>{/if}
    </div>
  {/if}
{/snippet}

<PageHeader eyebrow="Concept · {c.concept_type}" title={c.name} description={c.summary}>
  {#snippet actions()}
    <form method="POST" action="/questions?/generate" class="flex flex-wrap items-center gap-2">
      <input type="hidden" name="type" value="sba" />
      <input type="hidden" name="count" value="5" />
      <input type="hidden" name="topic" value={c.name} />
      <label class="sr-only" for="quiz-exam">Exam</label>
      <select id="quiz-exam" name="exam_target" class="field min-h-9 w-auto py-1.5 text-sm">
        {#each EXAM_TARGETS as target (target.value)}<option value={target.value}>{target.label}</option>{/each}
      </select>
      <button class="btn btn-primary min-h-9 px-3 py-1.5 text-sm" type="submit" title="Five cited single-best-answer questions on this concept">
        Quiz me
      </button>
    </form>
    <a href="/knowledge" class="btn btn-ghost">All concepts</a>
  {/snippet}
</PageHeader>

<div class="flex flex-col gap-8">
  <p class="flex flex-wrap gap-2 text-sm text-ink-2">
    {#if c.curriculum_code}
      <span class="rounded-lg border border-line px-2.5 py-1">
        Curriculum <span class="font-mono">{c.curriculum_code}</span>{c.curriculum_confidence !== null ? ` · ${percent(c.curriculum_confidence)} confident` : ''}
      </span>
    {/if}
    {#each c.aliases as alias (alias)}<span class="rounded-lg bg-surface-2 px-2.5 py-1">{alias}</span>{/each}
  </p>

  <section aria-labelledby="note-heading">
    <h2 id="note-heading" class="mb-3 text-xl font-semibold text-ink">Concept note</h2>
    {@render feedback('note')}
    {#if data.noteProblem}
      <LoadIssue compact problem={data.noteProblem} title="The note is unreachable" icon="knowledge" />
    {:else}
      <ConceptNote info={data.note} claims={c.claims} />
    {/if}
  </section>

  <section aria-labelledby="ddx-heading">
    <h2 id="ddx-heading" class="mb-3 text-xl font-semibold text-ink">Differential tree</h2>
    <DdxTree name={c.name} {branches} {numbers} />
  </section>

  <section aria-labelledby="graph-heading">
    <h2 id="graph-heading" class="mb-3 text-xl font-semibold text-ink">Concept map</h2>
    {#if data.graph}<ConceptGraph graph={data.graph} />{:else}<p class="text-sm text-muted">The concept map is unavailable.</p>{/if}
  </section>

  {#if data.figures.length}
    <section aria-labelledby="figures-heading">
      <h2 id="figures-heading" class="mb-3 text-xl font-semibold text-ink">Related figures</h2>
      <ul class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {#each data.figures as figure (figure.figure_id)}<FigureHitCard {figure} actions={false} />{/each}
      </ul>
    </section>
  {/if}

  <section aria-labelledby="claims-heading">
    <h2 id="claims-heading" class="mb-3 text-xl font-semibold text-ink">Claims ({claims.length})</h2>
    {#if claims.length === 0}
      <p class="text-sm text-muted">No verified claims for this concept yet.</p>
    {:else}
      <ol class="flex flex-col gap-3">
        {#each claims as claim (claim.id)}
          <li class="panel p-4">
            <p class="flex flex-wrap items-center gap-2">
              <span class="label">{claim.claim_type.replace(/_/g, ' ')}{claim.modality ? ` · ${claim.modality}` : ''}</span>
              <StatusBadge status={claim.status} />
              {#if claim.verification}<span class="label">{claim.verification}</span>{/if}
            </p>
            <p class="mt-1.5 text-[0.9375rem] leading-relaxed text-ink">{claim.statement}</p>
            {#if claim.evidence_span}<p class="mt-1 text-sm text-ink-2 italic">“{claim.evidence_span}”</p>{/if}
            <div class="mt-2 flex flex-wrap gap-1.5">
              <CitationChip citation={claim.citation} />
              <CitationList citations={claim.supporting} />
            </div>
          </li>
        {/each}
      </ol>
    {/if}
  </section>

  {#if c.edges.length}
    <section aria-labelledby="edges-heading">
      <h2 id="edges-heading" class="mb-3 text-xl font-semibold text-ink">Related concepts</h2>
      <ul class="flex flex-col divide-y divide-line">
        {#each c.edges as edge (edge.id)}
          <li class="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span class="label">{edge.direction === 'out' ? edge.relation.replace(/_/g, ' ') : `← ${edge.relation.replace(/_/g, ' ')}`}</span>
            <a class="link" href="/knowledge/{edge.other_id}">{edge.other_name}</a>
            <CitationChip citation={edge.citation} />
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <section aria-labelledby="conflicts-heading">
    <h2 id="conflicts-heading" class="mb-3 text-xl font-semibold text-ink">Source conflicts</h2>
    {@render feedback('resolve')}
    {#if c.conflicts.length === 0}
      <p class="text-sm text-muted">Your sources agree on this concept.</p>
    {:else}
      <ul class="flex flex-col gap-4">
        {#each c.conflicts as conflict (conflict.id)}<ConflictCard {conflict} />{/each}
      </ul>
    {/if}
  </section>
</div>
