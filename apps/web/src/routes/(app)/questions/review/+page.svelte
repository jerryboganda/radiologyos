<script lang="ts">
  import { enhance } from '$app/forms';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import QuestionTabs from '$lib/components/questions/QuestionTabs.svelte';
  import ReviewCard from '$lib/components/questions/ReviewCard.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let reviewed = $derived(form && 'reviewed' in form && form.reviewed ? form.reviewed : null);
  const DONE: Record<string, string> = {
    approve: 'Approved: the question is now in your bank and can appear in exams.',
    reject: 'Rejected: the question was retired.',
    edit: 'Edits saved. Approve the draft when it reads correctly.'
  };
</script>

<svelte:head><title>Review drafts · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Questions"
  title="Review drafts"
  description="Drafts are generated items the independent checker did not pass. Review each against its cited sources: approve it into your bank, fix the wording, or reject it. Approval needs every cited page to still exist."
/>

<QuestionTabs current="review" />

<div class="flex flex-col gap-6">
  <section class="panel flex flex-wrap items-center justify-between gap-3 p-4" aria-label="Item statistics">
    <p class="max-w-xl text-sm text-ink-2">
      Item statistics retire questions that are too easy, too hard, or not discriminating after 50 attempts. They refresh after each exam; recompute now if needed.
    </p>
    <form method="POST" action="?/stats" use:enhance>
      <button class="btn btn-ghost" type="submit">Recompute statistics</button>
    </form>
  </section>
  {#if form && 'stats' in form && form.stats}
    <Notice tone="ok">Statistics updated for {form.stats.computed} question{form.stats.computed === 1 ? '' : 's'}; {form.stats.retired} retired.</Notice>
  {/if}
  {#if form && 'statsError' in form && form.statsError}<Notice tone="warn">{form.statsError}</Notice>{/if}
  {#if reviewed}<Notice tone="ok">{DONE[reviewed] ?? 'Saved.'}</Notice>{/if}

  {#if data.problem}
    <LoadIssue problem={data.problem} title="The review queue is unreachable" icon="questions" />
  {:else if data.drafts.length === 0}
    <div class="panel px-6 py-12 text-center">
      <p class="font-display text-xl text-ink">No drafts to review.</p>
      <p class="mt-2 text-sm text-muted">Items the checker passes go straight to your bank.</p>
    </div>
  {:else}
    <ol class="flex flex-col gap-5">
      {#each data.drafts as item (item.id)}
        {@const mine = form && 'questionId' in form && form.questionId === item.id}
        <li><ReviewCard {item} error={mine && 'error' in form ? form.error : null} /></li>
      {/each}
    </ol>
  {/if}
</div>
