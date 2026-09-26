<script lang="ts">
  import { enhance } from '$app/forms';
  import CitationList from '$lib/components/CitationList.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import PageViewer from '$lib/components/reader/PageViewer.svelte';
  import StagedCase from '$lib/components/viva/StagedCase.svelte';
  import VivaChat from '$lib/components/viva/VivaChat.svelte';
  import VivaDebrief from '$lib/components/viva/VivaDebrief.svelte';
  import VivaTimer from '$lib/components/viva/VivaTimer.svelte';
  import { pollWhile } from '$lib/poll.svelte';
  import { mediaUrl } from '$lib/viewer';
  import { isWaiting, styleLabel } from '$lib/viva';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
  let session = $derived(data.session);
  let image = $derived(mediaUrl(session.figure_image_path));
  let staged = $derived(session.kind === 'image_case');
  let ended = $derived(session.status === 'finished' || session.status === 'failed');
  let draft = $derived(form && 'draft' in form ? String(form.draft ?? '') : '');
  let ending = $state(false);

  pollWhile(() => isWaiting(data.session), 'app:viva', 2000, 6000);
</script>

<svelte:head><title>{staged ? 'Image case' : 'Viva'} · radbrain</title></svelte:head>

<header class="mb-6 flex flex-wrap items-start justify-between gap-3">
  <div class="min-w-0">
    <p class="label"><a class="link" href="/viva">Viva</a> · {styleLabel(session.style)}</p>
    <h1 class="mt-1 font-display text-2xl text-ink sm:text-3xl">
      {staged ? 'Staged image case' : 'Viva'}{session.topic ? `: ${session.topic}` : ''}
    </h1>
  </div>
  <div class="flex items-center gap-2">
    {#if session.deadline_at && !ended}
      <VivaTimer deadlineAt={session.deadline_at} serverTime={session.server_time} />
    {/if}
    <StatusBadge status={session.status} />
    {#if !ended}
      <form
        method="POST"
        action="?/end"
        use:enhance={({ cancel }) => {
          if (!confirm('End this session now? Unanswered questions will be marked as not answered.')) {
            cancel();
            return;
          }
          ending = true;
          return async ({ update }) => {
            await update();
            ending = false;
          };
        }}
      >
        <button class="btn btn-ghost" type="submit" disabled={ending}>{ending ? 'Ending…' : 'End'}</button>
      </form>
    {/if}
  </div>
</header>

{#if form?.error}<div class="mb-4"><Notice tone="warn">{form.error}</Notice></div>{/if}

<div class="grid gap-6 {image ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]' : ''}">
  {#if image}
    <div class="lg:sticky lg:top-4 lg:self-start">
      <PageViewer
        src={image}
        alt="Case image"
        corner="Case image"
        blocks={[]}
        figures={[]}
        selected={null}
        blocksToggle={false}
        onselect={() => {}}
      />
    </div>
  {/if}

  <div class="flex min-w-0 flex-col gap-5">
    {#if session.status === 'preparing'}
      <p class="panel p-5 text-ink-2" role="status">
        <span class="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true"></span>
        {staged ? 'Writing the station rubric from your sources…' : 'The examiner is reading your sources…'}
        {#if session.error_code}<span class="mt-1 block text-sm text-muted">Waiting to retry ({session.error_code.replace(/_/g, ' ')}).</span>{/if}
      </p>
    {:else if session.status === 'failed'}
      <Notice tone="warn">
        The examiner could not start this session ({(session.error_code ?? 'error').replace(/_/g, ' ')}). Nothing uncited was
        shown. Try again later or pick another topic.
      </Notice>
    {/if}

    {#if session.scenario}
      <section class="panel p-5" aria-label="Scenario">
        <p class="label">{staged ? 'Station' : 'Scenario'}</p>
        <p class="mt-1 text-[0.9375rem] leading-relaxed whitespace-pre-line text-ink">{session.scenario}</p>
        <CitationList citations={session.scenario_citations} class="mt-2" />
      </section>
    {/if}

    {#if session.debrief}
      <VivaDebrief debrief={session.debrief} kind={session.kind} />
    {/if}

    {#if session.turns.length}
      {#if staged}
        <StagedCase {session} {draft} />
      {:else}
        <VivaChat {session} {draft} />
      {/if}
    {/if}
  </div>
</div>
