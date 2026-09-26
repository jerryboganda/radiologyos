<script lang="ts">
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import QuestionCard from '$lib/components/QuestionCard.svelte';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Questions · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Questions"
  title="Single best answer practice"
  description="Every question is generated from and cited to your sources. Explanations link to the exact page."
>
  {#snippet actions()}
    <a href="/questions" class="btn btn-ghost" data-sveltekit-reload>New set</a>
  {/snippet}
</PageHeader>

{#if data.detail}
  <Notice tone="danger">{data.detail}</Notice>
{:else if !data.online}
  <ComingOnline
    title="The question bank is coming online"
    description="SBA and image-based questions, each with a cited explanation, will appear here once the assessment service is deployed."
    endpoints={['/v1/questions', '/v1/questions/{id}/attempts']}
    icon="questions"
  />
{:else if data.questions.length === 0}
  <div class="panel px-6 py-12 text-center">
    <p class="font-display text-xl text-ink">No questions yet.</p>
    <p class="mt-2 text-sm text-muted">Questions are written from your processed sources. Add more to the library.</p>
  </div>
{:else}
  <ol class="flex flex-col gap-5">
    {#each data.questions as question, i (question.id)}
      {@const mine = form?.questionId === question.id}
      <QuestionCard
        {question}
        number={i + 1}
        feedback={mine && form && 'result' in form ? form.result : null}
        chosen={mine && form && 'choice' in form ? form.choice : null}
        error={mine && form && 'error' in form ? form.error : null}
      />
    {/each}
  </ol>
{/if}
