<script lang="ts">
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import SignedOut from '$lib/components/shell/SignedOut.svelte';
  import Onboarding from '$lib/components/study/Onboarding.svelte';
  import ReviewDeck from '$lib/components/study/ReviewDeck.svelte';
  import TodayPlan from '$lib/components/study/TodayPlan.svelte';
  import { daysUntil, formatDate } from '$lib/format';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

  let firstName = $derived(data.user?.name.split(/\s+/)[0] ?? '');
  let days = $derived(data.signedIn ? daysUntil(data.profile?.exam_date) : null);
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

  {#if form && 'error' in form && form.error}
    <div class="mb-5"><Notice tone="warn">{form.error}</Notice></div>
  {/if}

  <div class="flex flex-col gap-6">
    {#if !data.studyOnline}
      <ComingOnline
        title="Your study planner is coming online"
        description="The daily plan, spaced-repetition reviews, and onboarding appear here as soon as the study service is deployed. Your library and search work today."
        endpoints={['/v1/study/profile', '/v1/study/today', '/v1/study/cards/due']}
        icon="today"
      />
    {:else if !data.profile?.exam_date}
      <Onboarding />
    {:else}
      <div class="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {#if data.today}<TodayPlan plan={data.today} />{:else}<ComingOnline compact title="Today’s plan is being prepared" description="Your plan appears once the planner has scheduled today." icon="today" />{/if}
        {#if data.due}<ReviewDeck cards={data.due.cards} total={data.due.total} />{:else}<ComingOnline compact title="Reviews coming online" description="Spaced-repetition cards appear here when the card service is live." endpoints={['/v1/study/cards/due']} icon="progress" />{/if}
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
