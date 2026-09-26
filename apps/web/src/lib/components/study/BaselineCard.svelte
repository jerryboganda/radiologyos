<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import { formatDate, percent } from '$lib/format';
  import type { BaselineOut } from '$lib/types/study';

  let { baseline, error = null }: { baseline: BaselineOut | null; error?: string | null } = $props();
  let busy = $state(false);
  let open = $derived(baseline?.status === 'open');
  let results = $derived(baseline?.status === 'submitted' ? baseline.results : []);
</script>

<section class="panel p-5 sm:p-6" aria-labelledby="baseline-heading">
  <h2 id="baseline-heading" class="text-xl font-semibold text-ink">Baseline test</h2>
  <p class="mt-1 text-sm text-ink-2">
    A short timed SBA test across systems, built from your checked questions. Your answers set each system's starting accuracy.
  </p>
  {#if open && baseline}
    <p class="mt-4 text-sm text-ink-2">
      {baseline.question_count} questions across {baseline.systems.length} system{baseline.systems.length === 1 ? '' : 's'} are waiting.
    </p>
    <a class="btn btn-primary mt-3 inline-flex h-11 items-center" href="/exams/{baseline.exam_id}">Resume baseline test</a>
  {:else}
    {#if results.length && baseline}
      <p class="label mt-4">Taken {formatDate(baseline.submitted_at)}</p>
      <ul class="mt-2 flex flex-wrap gap-1.5">
        {#each results as result (result.code)}
          <li class="rounded-lg border border-line px-2.5 py-1 text-xs text-ink-2">
            {result.title} · <span class="font-mono text-ink">{percent(result.accuracy)}</span>
            <span class="text-muted">({result.questions})</span>
          </li>
        {/each}
      </ul>
    {/if}
    <form
      method="POST"
      action="?/baseline"
      class="mt-4"
      use:enhance={() => {
        busy = true;
        return async ({ update }) => {
          await update();
          busy = false;
        };
      }}
    >
      <button class="btn btn-primary h-11" type="submit" disabled={busy}>
        {busy ? 'Building your test…' : results.length ? 'Retake baseline test' : 'Take baseline test'}
      </button>
    </form>
  {/if}
  {#if error}<div class="mt-3"><Notice tone="warn">{error}</Notice></div>{/if}
</section>
