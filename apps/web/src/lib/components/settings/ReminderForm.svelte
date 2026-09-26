<script lang="ts">
  import { enhance } from '$app/forms';
  import { DEFAULT_REMINDERS, type ReminderPrefs } from '$lib/types/settings';

  let { prefs, online }: { prefs: ReminderPrefs | null; online: boolean } = $props();
  let value = $derived(prefs ?? DEFAULT_REMINDERS);
  let timezone = $state('UTC');
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  $effect(() => {
    timezone = prefs?.timezone && prefs.timezone !== 'UTC' ? prefs.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone;
  });
</script>

<form method="POST" action="?/reminders" use:enhance class="flex flex-col gap-4">
  <label class="flex items-center gap-3">
    <input type="checkbox" name="enabled" checked={value.enabled} class="h-5 w-5 accent-[var(--accent)]" />
    <span class="text-sm text-ink">Send me a daily study reminder</span>
  </label>
  <div class="grid gap-4 sm:grid-cols-[10rem_1fr]">
    <label class="block">
      <span class="label">Time</span>
      <input type="time" name="time_of_day" value={value.time_of_day} required class="field mt-1.5 font-mono" />
    </label>
    <fieldset>
      <legend class="label">Days</legend>
      <div class="mt-1.5 flex flex-wrap gap-1.5">
        {#each DAYS as day, i (day)}
          <label
            class="cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]"
          >
            <input type="checkbox" name="days" value={i} checked={value.days.includes(i)} class="sr-only" />{day}
          </label>
        {/each}
      </div>
    </fieldset>
  </div>
  <input type="hidden" name="timezone" value={timezone} />
  <p class="text-xs text-muted">Time zone: <span class="font-mono">{timezone}</span></p>
  <div>
    <button type="submit" class="btn btn-primary">Save reminders</button>
    {#if !online}
      <p class="mt-2 text-xs text-warn">
        TODO (API): <code class="font-mono">/v1/notifications/preferences</code> is not deployed yet, so saving will report that nothing was stored.
      </p>
    {/if}
  </div>
</form>
