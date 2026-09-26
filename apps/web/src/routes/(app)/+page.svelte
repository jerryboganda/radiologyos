<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import SignedOut from '$lib/components/shell/SignedOut.svelte';
  import BaselineCard from '$lib/components/study/BaselineCard.svelte';
  import GenerateCards from '$lib/components/study/GenerateCards.svelte';
  import KnowledgeCards from '$lib/components/study/KnowledgeCards.svelte';
  import { knowledgeSummary } from '$lib/cards';
  import Onboarding from '$lib/components/study/Onboarding.svelte';
  import ReviewDeck from '$lib/components/study/ReviewDeck.svelte';
  import SessionRunner from '$lib/components/study/session/SessionRunner.svelte';
  import TodayPlan from '$lib/components/study/TodayPlan.svelte';
  import { daysUntil, formatDate } from '$lib/format';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let firstName = $derived(data.user?.name.split(/\s+/)[0] ?? '');
  let days = $derived(data.signedIn ? (data.profile?.days_remaining ?? daysUntil(data.profile?.exam_date)) : null);
  function errorFor(section: string): string | null {
    return form && form.section === section && 'error' in form ? (form.error ?? null) : null;
  }
  let scheduledDays = $derived(form && 'scheduledDays' in form ? (form.scheduledDays ?? null) : null);
  let generated = $derived(
    form && 'created' in form
      ? `Created ${form.created} card${form.created === 1 ? '' : 's'} from ${form.chunksUsed} passage${form.chunksUsed === 1 ? '' : 's'}${form.rejected ? ` (${form.rejected} rejected by the checker)` : ''}.`
      : null
  );
  let madeFromKnowledge = $derived(
    form && 'made' in form ? knowledgeSummary(form.kind ?? 'cloze', form.made ?? 0, form.skipped ?? 0) : null
  );
  // Local time is only known in the browser; render a neutral greeting on the server.
  let now = $state<Date | null>(null);
  $effect(() => {
    now = new Date();
  });
  let greeting = $derived.by(() => {
    if (!now) return 'Welcome back';
    const hour = now.getHours();
    return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  });
</script>

<svelte:head>
  <title>{data.signedIn ? 'Today · radbrain' : 'radbrain'}</title>
</svelte:head>

{#if !data.signedIn}
  <SignedOut authEnabled={data.authEnabled} authError={data.authError} />
{:else}
  <header class="mb-8 flex flex-wrap items-end justify-between gap-6">
    <div>
      <p class="label">{now ? now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) : 'Today'}</p>
      <h1 class="mt-2 text-3xl font-semibold text-ink sm:text-4xl">{greeting}, {firstName}.</h1>
    </div>
    {#if days !== null}
      <div class="flex items-baseline gap-3 rounded-2xl border border-line bg-surface px-5 py-3">
        <span class="font-display text-5xl leading-none font-semibold text-accent tabular-nums">{Math.max(days, 0)}</span>
        <span class="text-sm leading-tight text-ink-2">days to<br />exam · <span class="font-mono text-xs text-muted">{formatDate(data.profile?.exam_date)}</span></span>
      </div>
    {/if}
  </header>

  <div class="flex flex-col gap-6">
    {#if data.onboarding}
      <Onboarding error={errorFor('onboard')} />
    {:else if data.todayProblem}
      <LoadIssue problem={data.todayProblem} title="Your study planner is unreachable" icon="today" />
    {:else}
      <div class="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div class="flex min-w-0 flex-col gap-6">
          {#if data.session}
            <SessionRunner session={data.session} error={errorFor('session')} reviewError={errorFor('review')} {scheduledDays} />
          {:else}
            {#if data.sessionProblem}
              <LoadIssue compact problem={data.sessionProblem} title="Today’s session is unreachable" icon="today" />
            {/if}
            {#if data.dueProblem}
              <LoadIssue compact problem={data.dueProblem} title="Reviews are unreachable" icon="progress" />
            {:else}
              <ReviewDeck cards={data.due ?? []} error={errorFor('review')} {scheduledDays} />
            {/if}
          {/if}
        </div>
        <div class="flex min-w-0 flex-col gap-6">
          {#if data.today}<TodayPlan plan={data.today} />{/if}
          <BaselineCard baseline={data.baseline} error={errorFor('baseline')} />
          <GenerateCards sources={data.sources} error={errorFor('generate')} summary={generated} />
          <KnowledgeCards sources={data.sources} error={errorFor('knowledge')} summary={madeFromKnowledge} />
        </div>
      </div>
    {/if}

    <section class="grid gap-3 sm:grid-cols-3" aria-label="Shortcuts">
      <a href="/library" class="panel group flex items-center gap-4 p-4 hover:border-accent">
        <Icon name="library" class="text-accent" />
        <span><span class="block font-medium text-ink">Library</span><span class="text-xs text-muted">{data.sourceCount ?? '—'} sources</span></span>
      </a>
      <a href="/search" class="panel group flex items-center gap-4 p-4 hover:border-accent">
        <Icon name="search" class="text-accent" />
        <span><span class="block font-medium text-ink">Search</span><span class="text-xs text-muted">Cited passages & figures</span></span>
      </a>
      <a href="/tutor" class="panel group flex items-center gap-4 p-4 hover:border-accent">
        <Icon name="tutor" class="text-accent" />
        <span><span class="block font-medium text-ink">Ask the tutor</span><span class="text-xs text-muted">Answers with citations</span></span>
      </a>
    </section>
  </div>
{/if}
