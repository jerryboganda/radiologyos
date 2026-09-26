<script lang="ts">
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate, percent } from '$lib/format';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
  let p = $derived(data.progress);
  let stats = $derived(
    p
      ? [
          ['Days to exam', String(Math.max(p.days_remaining, 0))],
          ['Due now', String(p.due_now)],
          ['Reviews today', String(p.reviews_today)],
          ['Retention', percent(p.retention)],
          ['Cards', String(p.cards)],
          ['New cards', String(p.new_cards)],
          ['Reviews total', String(p.reviews_total)],
          ['Phase', p.phase.replace(/_/g, ' ')]
        ]
      : []
  );
  const COLUMNS = ['Topic', 'Band', 'Mastery', 'Accuracy', 'Recall', 'Coverage', 'Cards', 'Lapses'];
</script>

<svelte:head><title>Progress · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Progress"
  title="How the preparation is going"
  description="Reviews, retention, and mastery by topic. No pass-probability is shown until it has been validated."
/>

{#if data.onboarding}
  <div class="panel px-6 py-10 text-center">
    <p class="font-display text-xl text-ink">Set your exam date first.</p>
    <p class="mt-2 text-sm text-muted">Progress is measured against your exam. <a class="link" href="/">Start on Today.</a></p>
  </div>
{:else if data.problem}
  <LoadIssue problem={data.problem} title="Progress is unreachable" icon="progress" />
{:else if p}
  <p class="label mb-3">Exam {formatDate(p.exam_date)}</p>
  <dl class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    {#each stats as [label, value] (label)}
      <div class="panel px-4 py-4">
        <dt class="label">{label}</dt>
        <dd class="mt-1 font-display text-3xl text-ink capitalize tabular-nums">{value}</dd>
      </div>
    {/each}
  </dl>
  {#if p.notice}<p class="mt-3 text-xs text-muted">{p.notice}</p>{/if}

  <section class="mt-6" aria-labelledby="topics-heading">
    <h2 id="topics-heading" class="mb-3 text-xl font-semibold text-ink">Topics</h2>
    {#if p.topics.length === 0}
      <p class="text-sm text-muted">Topic mastery appears after your first reviews.</p>
    {:else}
      <div class="panel overflow-x-auto">
        <table class="w-full min-w-[44rem] text-left text-sm">
          <thead class="label border-b border-line">
            <tr>{#each COLUMNS as column (column)}<th class="px-4 py-3 font-normal">{column}</th>{/each}</tr>
          </thead>
          <tbody class="divide-y divide-line">
            {#each p.topics as topic (topic.code)}
              <tr>
                <td class="px-4 py-3 text-ink"><span class="font-mono text-xs text-muted">{topic.code}</span> {topic.title}</td>
                <td class="px-4 py-3 text-xs text-ink-2">{topic.band}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2">
                    <div class="h-1.5 w-20 overflow-hidden rounded-full bg-surface-2"><div class="h-full bg-ok" style="width: {Math.min(Math.max(topic.mastery, 0), 1) * 100}%"></div></div>
                    <span class="font-mono text-xs text-ink-2">{percent(topic.mastery)}</span>
                  </div>
                </td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{percent(topic.accuracy)}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{percent(topic.retrievability)}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{percent(topic.coverage)}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.cards}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-2">{topic.lapses}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
