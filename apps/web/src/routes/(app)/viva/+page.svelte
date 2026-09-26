<script lang="ts">
  import LoadIssue from '$lib/components/LoadIssue.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import VivaStart from '$lib/components/viva/VivaStart.svelte';
  import { formatDate } from '$lib/format';
  import { STOP_REASONS, styleLabel } from '$lib/viva';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Viva · radbrain</title></svelte:head>

<PageHeader
  eyebrow="Viva"
  title="Viva and TOACS practice"
  description="An examiner questions you turn by turn from your own sources: good answers go one level deeper, weak ones get a probe with a hint, and two misses in a row end it. Staged image cases take you through describe, findings, diagnosis, differentials, and next step. Every model answer and teaching point cites your library."
/>

<div class="flex flex-col gap-8">
  <VivaStart prefill={data.prefill} error={form?.error ?? null} />

  <section aria-labelledby="recent-heading">
    <h2 id="recent-heading" class="mb-3 text-xl font-semibold text-ink">Recent sessions</h2>
    {#if data.problem}
      <LoadIssue problem={data.problem} title="Viva sessions are unreachable" icon="tutor" />
    {:else if data.sessions.length === 0}
      <p class="text-sm text-muted">No sessions yet. Start one above.</p>
    {:else}
      <ul class="grid gap-3 sm:grid-cols-2">
        {#each data.sessions as session (session.id)}
          <li>
            <a href="/viva/{session.id}" class="panel flex items-center justify-between gap-3 p-4 hover:border-accent">
              <span class="min-w-0">
                <span class="block truncate font-medium text-ink">
                  {session.kind === 'image_case' ? 'Image case' : styleLabel(session.style)}{session.topic ? ` · ${session.topic}` : ''}
                </span>
                <span class="label">
                  {formatDate(session.started_at)}{session.overall_percent !== null ? ` · ${session.overall_percent}%` : ''}{session.stop_reason
                    ? ` · ${STOP_REASONS[session.stop_reason] ?? session.stop_reason}`
                    : ''}
                </span>
              </span>
              <StatusBadge status={session.status} />
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>
