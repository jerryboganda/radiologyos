<script lang="ts">
  import { enhance } from '$app/forms';
  import AnswerView from '$lib/components/AnswerView.svelte';
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate } from '$lib/format';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let asking = $state(false);
  let answer = $derived(form && 'answer' in form ? form.answer : null);
  let threadId = $derived(answer?.thread_id ?? data.thread?.id ?? '');
  let turns = $derived(data.thread?.turns ?? []);
</script>

<svelte:head><title>Tutor · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Tutor"
  title="Ask your library"
  description="Answers are built only from cited passages. Anything from the web is labelled and linked; anything uncited is flagged."
/>

{#if !data.online}
  <div class="mb-6">
    <ComingOnline
      title="The tutor is coming online"
      description="Grounded answers with page-level citations will appear here once the tutor service is deployed. Until then, Search returns the same cited passages directly."
      endpoints={['/v1/tutor/ask', '/v1/tutor/threads']}
      icon="tutor"
    />
  </div>
{/if}

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
  <div class="flex min-w-0 flex-col gap-5">
    {#each turns as turn, i (i)}<AnswerView answer={turn} />{/each}
    {#if answer}<AnswerView {answer} />{/if}

    {#if form && 'error' in form && form.error}<Notice tone="warn">{form.error}</Notice>{/if}

    <form
      method="POST"
      action="?/ask"
      class="panel sticky bottom-24 flex flex-col gap-3 p-3 shadow-lg lg:bottom-6"
      use:enhance={() => {
        asking = true;
        return async ({ update }) => {
          await update();
          asking = false;
        };
      }}
    >
      <input type="hidden" name="thread_id" value={threadId} />
      <label for="question" class="sr-only">Your question</label>
      <textarea
        id="question"
        name="question"
        rows="3"
        required
        minlength="3"
        maxlength="2000"
        placeholder="e.g. What distinguishes a Bosniak IIF from a III cyst on CT?"
        class="field resize-y text-[0.9375rem]"
        value={form && 'question' in form ? (form.question ?? '') : ''}
      ></textarea>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <label class="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" name="allow_web" class="h-4 w-4 accent-[var(--accent)]" />
          Allow labelled web sources
        </label>
        <button class="btn btn-primary" type="submit" disabled={asking}>{asking ? 'Thinking…' : 'Ask'}</button>
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
              <span class="label">{formatDate(thread.updated_at)}</span>
            </a>
          </li>
        {/each}
      </ul>
      <a href="/tutor" class="link mt-3 inline-block text-sm">New thread</a>
    {/if}
  </aside>
</div>
