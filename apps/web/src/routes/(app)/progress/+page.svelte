<script lang="ts">
  import ComingOnline from '$lib/components/ComingOnline.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { percent } from '$lib/format';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
  let p = $derived(data.progress);
  let recent = $derived(p ? p.history.slice(-14) : []);
  let peak = $derived(Math.max(30, ...recent.map((d) => d.minutes)));
</script>

<svelte:head><title>Progress · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Progress"
  title="How the preparation is going"
  description="Consistency, retention, and coverage by topic. No pass-probability is shown until it has been validated."
/>

{#if data.detail}
  <Notice tone="danger">{data.detail}</Notice>
{:else if !p}
  <ComingOnline
    title="Progress tracking is coming online"
    description="Streaks, review retention, and topic mastery will appear here once the study service is deployed."
    endpoints={['/v1/study/progress']}
    icon="progress"
  />
{:else}
  <dl class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    {#each [['Streak', `${p.streak_days} d`], ['Reviews · 7 d', String(p.reviews_7d)], ['Study time · 7 d', `${Math.round(p.minutes_7d / 60)} h ${p.minutes_7d % 60} m`], ['Retention · 30 d', percent(p.retention_30d)]] as [label, value] (label)}
      <div class="panel px-4 py-4">
        <dt class="label">{label}</dt>
        <dd class="mt-1 font-display text-3xl text-ink tabular-nums">{value}</dd>
      </div>
    {/each}
  </dl>

  {#if recent.length}
    <section class="panel mt-6 p-5" aria-labelledby="activity-heading">
      <h2 id="activity-heading" class="label">Minutes per day · last {recent.length} days</h2>
      <div class="mt-4 flex h-32 items-end gap-1.5" role="img" aria-label="Daily study minutes">
        {#each recent as day (day.date)}
          <div class="flex h-full flex-1 flex-col justify-end" title="{day.date}: {day.minutes} min, {day.reviews} reviews">
            <div class="rounded-t-sm bg-accent/80" style="height: {Math.max(2, (day.minutes / peak) * 100)}%"></div>
          </div>
        {/each}
      </div>
      <table class="sr-only">
        <caption>Daily study minutes</caption>
        <tbody>{#each recent as day (day.date)}<tr><th>{day.date}</th><td>{day.minutes} minutes</td></tr>{/each}</tbody>
      </table>
    </section>
  {/if}

  <section class="mt-6" aria-labelledby="topics-heading">
    <h2 id="topics-heading" class="mb-3 text-xl font-semibold text-ink">Topics</h2>
    {#if p.topics.length === 0}
      <p class="text-sm text-muted">Topic mastery appears after your first reviews.</p>
    {:else}
      <div class="panel overflow-x-auto">
        <table class="w-full min-w-[34rem] text-left text-sm">
          <thead class="label border-b border-line">
            <tr><th class="px-4 py-3 font-normal">Topic</th><th class="px-4 py-3 font-normal">Weight</th><th class="px-4 py-3 font-normal">Mastery</th><th class="px-4 py-3 font-normal">Coverage</th><th class="px-4 py-3 font-normal">Due</th></tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each p.topics as topic (topic.code)}
              <tr>
                <td class="px-4 py-3 text-ink"><span class="font-mono text-xs text-muted">{topic.code}</span> {topic.name}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{percent(topic.weight)}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2">
                    <div class="h-1.5 w-24 overflow-hidden rounded-full bg-surface-2"><div class="h-full bg-ok" style="width: {(topic.mastery ?? 0) * 100}%"></div></div>
                    <span class="font-mono text-xs text-ink-2">{percent(topic.mastery)}</span>
                  </div>
                </td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{percent(topic.coverage)}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.due}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
