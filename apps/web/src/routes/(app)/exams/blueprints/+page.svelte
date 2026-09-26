<script lang="ts">
  import BlueprintCard from '$lib/components/exams/BlueprintCard.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Exam blueprints · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Exams"
  title="Exam blueprints"
  description="Question counts, time, per-system mix, and marking for each paper, drawn from CPSP and RCR public guidance. Anything a public source did not confirm is marked unverified. Adjust it to match your notification, then approve."
/>

<p class="-mt-2 mb-6 text-sm">
  <a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/exams">← Back to exams</a>
  <span class="mx-2 text-muted">·</span>
  <a class="text-ink-2 underline underline-offset-2 hover:text-ink" href="/knowledge/curriculum">Curriculum tree →</a>
</p>

{#if form}
  <div class="mb-4">
    {#if 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{:else if 'message' in form && form.message}<Notice tone="ok"
        >{form.message}</Notice
      >{/if}
  </div>
{/if}

{#if data.problem}
  <LoadIssue problem={data.problem} title="Blueprints are unreachable" icon="exams" />
{:else}
  <p class="label mb-3">Only the account owner or an admin can change or approve a blueprint.</p>
  <ul class="grid gap-4 lg:grid-cols-2">
    {#each data.blueprints as blueprint (blueprint.id)}<BlueprintCard {blueprint} />{/each}
  </ul>
{/if}
