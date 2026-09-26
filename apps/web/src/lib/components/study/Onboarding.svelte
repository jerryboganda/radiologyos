<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';
  import { EXAM_TARGETS } from '$lib/types/study';

  let { error = null, action = '?/onboard' }: { error?: string | null; action?: string } = $props();
  let timezone = $state('');
  let saving = $state(false);
  const today = new Date().toISOString().slice(0, 10);

  $effect(() => {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  });
</script>

<section class="panel overflow-hidden" aria-labelledby="onboard-heading">
  <div class="border-b border-line bg-surface-2/60 px-6 py-5 sm:px-8">
    <p class="label">Set up · step 1 of 1</p>
    <h2 id="onboard-heading" class="mt-1 text-2xl font-semibold text-ink">When is your exam?</h2>
    <p class="mt-1 max-w-prose text-sm text-ink-2">
      Everything is planned backwards from this date: what to read, what to review, and when to switch to mocks.
    </p>
  </div>
  <form
    method="POST"
    {action}
    class="grid gap-5 px-6 py-6 sm:grid-cols-2 sm:px-8"
    use:enhance={() => {
      saving = true;
      return async ({ update }) => {
        await update();
        saving = false;
      };
    }}
  >
    <label class="block">
      <span class="label">Exam date</span>
      <input name="exam_date" type="date" min={today} required class="field mt-1.5 font-mono" />
    </label>
    <label class="block">
      <span class="label">Study minutes per day</span>
      <input name="daily_minutes" type="number" min="15" max="600" step="5" value="90" required class="field mt-1.5 font-mono" />
    </label>
    <fieldset class="sm:col-span-2">
      <legend class="label">Exams you are sitting</legend>
      <div class="mt-1.5 flex flex-wrap gap-2">
        {#each EXAM_TARGETS as target, i (target.value)}
          <label
            class="cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]"
          >
            <input type="checkbox" name="exam_targets" value={target.value} checked={i === 0} class="sr-only" />{target.label}
          </label>
        {/each}
      </div>
    </fieldset>
    <input type="hidden" name="timezone" value={timezone} />
    <div class="sm:col-span-2">
      <button class="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Build my plan'}</button>
    </div>
  </form>
  {#if error}
    <div class="px-6 pb-6 sm:px-8"><Notice tone="warn">{error}</Notice></div>
  {/if}
</section>
