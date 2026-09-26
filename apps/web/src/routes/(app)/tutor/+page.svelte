<script lang="ts">
  import { enhance } from '$app/forms';
  import { goto } from '$app/navigation';
  import AnswerView from '$lib/components/AnswerView.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import TutorProgress from '$lib/components/TutorProgress.svelte';
  import { formatDate } from '$lib/format';
  import { readTutorStream } from '$lib/tutor-stream';
  import type { SubmitFunction } from '@sveltejs/kit';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let asking = $state(false);
  let allowWeb = $state(true);
  let stages = $state<string[]>([]);
  let pending = $state('');
  let streamError = $state<string | null>(null);
  let questionBox = $state<HTMLTextAreaElement | null>(null);
  let threadId = $derived(data.thread?.id ?? '');
  let messages = $derived(data.thread?.messages ?? []);

  // Stream progress over SSE; 'fallback' means the stream itself failed and
  // the JSON form action should answer instead.
  async function streamAsk(formData: FormData): Promise<'handled' | 'fallback'> {
    let response: Response;
    try {
      response = await fetch('/tutor/stream', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
        body: JSON.stringify({
          question: formData.get('question'),
          thread_id: formData.get('thread_id'),
          allow_web: formData.get('allow_web') === 'on'
        })
      });
    } catch {
      return 'fallback';
    }
    if (!response.ok || !response.body) return 'fallback';
    const outcome = await readTutorStream(response.body, (stage) => (stages = [...stages, stage]));
    if (outcome.kind === 'broken') return 'fallback';
    if (outcome.kind === 'error') {
      streamError = outcome.message;
      return 'handled';
    }
    await goto(`/tutor?thread=${encodeURIComponent(outcome.answer.thread_id)}`, { invalidateAll: true, noScroll: true });
    if (questionBox) questionBox.value = '';
    return 'handled';
  }

  const submit: SubmitFunction = async ({ formData, cancel }) => {
    asking = true;
    streamError = null;
    stages = [];
    pending = String(formData.get('question') ?? '').trim();
    const streamed = await streamAsk(formData);
    stages = [];
    pending = '';
    if (streamed === 'handled') {
      cancel();
      asking = false;
      return;
    }
    return async ({ update }) => {
      await update();
      asking = false;
    };
  };
</script>

<svelte:head><title>Tutor · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Tutor"
  title={data.thread?.title ?? 'Ask your library'}
  description="Answers are built only from cited passages and figures, and each sentence is checked against what it cites. Anything from the web is labelled and linked; unsupported sentences are removed."
>
  {#snippet actions()}
    {#if data.thread}<a href="/tutor" class="btn btn-ghost">New thread</a>{/if}
  {/snippet}
</PageHeader>

{#if data.problem}
  <div class="mb-6"><LoadIssue problem={data.problem} title="The tutor is unreachable" icon="tutor" /></div>
{/if}
{#if data.threadProblem}<div class="mb-6"><Notice tone="warn">{data.threadProblem}</Notice></div>{/if}

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
  <div class="flex min-w-0 flex-col gap-5">
    {#each messages as message (message.id)}
      {#if message.role === 'user'}
        <p class="self-end rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[0.9375rem] text-ink">{message.content}</p>
      {:else}
        <AnswerView segments={message.segments} grounding={message.grounding} fallback={message.content} judge={message.judge ?? null} />
      {/if}
    {/each}

    {#if asking && stages.length}<TutorProgress question={pending} stages={stages} />{/if}
    {#if streamError}<Notice tone="warn">{streamError}</Notice>{:else if form?.error}<Notice tone="warn">{form.error}</Notice>{/if}

    <form
      method="POST"
      action="?/ask"
      class="panel sticky bottom-24 flex flex-col gap-3 p-3 shadow-lg lg:bottom-6"
      use:enhance={submit}
    >
      <input type="hidden" name="thread_id" value={threadId} />
      <label for="question" class="sr-only">Your question</label>
      <textarea
        id="question"
        bind:this={questionBox}
        name="question"
        rows="3"
        required
        minlength="3"
        maxlength="2000"
        placeholder={threadId ? 'Ask a follow-up…' : 'e.g. What distinguishes a Bosniak IIF from a III cyst on CT?'}
        class="field resize-y text-[0.9375rem]"
        value={form?.question ?? ''}
      ></textarea>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <label class="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" name="allow_web" bind:checked={allowWeb} class="h-4 w-4 accent-[var(--accent)]" />
          Allow labelled web sources
        </label>
        <button class="btn btn-primary" type="submit" disabled={asking}>{asking ? 'Thinking… this can take a minute' : 'Ask'}</button>
      </div>
    </form>
  </div>

  <aside aria-labelledby="threads-heading">
    <h2 id="threads-heading" class="label mb-3">Recent threads</h2>
    {#if data.threads.length === 0}
      <p class="text-sm text-muted">No threads yet.</p>
    {:else}
      <ul class="flex flex-col gap-1">
        {#each data.threads as thread (thread.id)}
          <li>
            <a
              href="/tutor?thread={encodeURIComponent(thread.id)}"
              class="block rounded-lg px-3 py-2 hover:bg-surface-2 {thread.id === data.thread?.id ? 'bg-surface-2' : ''}"
            >
              <span class="line-clamp-2 text-sm text-ink">{thread.title}</span>
              <span class="label">{formatDate(thread.updated_at)} · {thread.message_count} messages</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>
</div>
