<script lang="ts">
  import { enhance } from '$app/forms';
  import Notice from '$lib/components/Notice.svelte';

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
    class="grid gap-5 px-6 py-6 sm:grid-cols-[1fr_1fr_auto] sm:items-end sm:px-8"
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
      <span class="label">Study time per day</span>
      <select name="daily_minutes" class="field mt-1.5">
        <option value="60">1 hour</option>
        <option value="90" selected>1 h 30 min</option>
        <option value="120">2 hours</option>
        <option value="180">3 hours</option>
      </select>
    </label>
    <input type="hidden" name="timezone" value={timezone} />
    <button class="btn btn-primary h-11" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Build my plan'}</button>
  </form>
  {#if error}
    <div class="px-6 pb-6 sm:px-8"><Notice tone="warn">{error}</Notice></div>
  {/if}
</section>
