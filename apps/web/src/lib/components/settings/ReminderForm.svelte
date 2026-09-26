<script lang="ts">
  import { enhance } from '$app/forms';
  import { fromApiTime } from '$lib/push';
  import { DEFAULT_SETTINGS, type NotificationSettings } from '$lib/types/settings';

  let { settings }: { settings: NotificationSettings | null } = $props();
  let value = $derived(settings ?? DEFAULT_SETTINGS);
  let timezone = $state('');
  let saving = $state(false);

  $effect(() => {
    timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || value.timezone;
  });

  const TOGGLES = [
    ['include_due_cards', 'Mention how many cards are due'],
    ['include_plan', 'Mention today’s plan']
  ] as const;
</script>

<form
  method="POST"
  action="?/reminders"
  class="flex flex-col gap-4"
  use:enhance={() => {
    saving = true;
    return async ({ update }) => {
      await update({ reset: false });
      saving = false;
    };
  }}
>
  <label class="flex items-center gap-3">
    <input type="checkbox" name="enabled" checked={value.enabled} class="h-5 w-5 accent-[var(--accent)]" />
    <span class="text-sm text-ink">Send me a daily study reminder</span>
  </label>
  <div class="grid gap-4 sm:grid-cols-[10rem_1fr]">
    <label class="block">
      <span class="label">Time</span>
      <input type="time" name="reminder_time" value={fromApiTime(value.reminder_time)} required class="field mt-1.5 font-mono" />
    </label>
    <fieldset>
      <legend class="label">Channels</legend>
      <div class="mt-1.5 flex flex-wrap gap-1.5">
        {#each [['push', 'Push'], ['email', 'Email']] as [channel, label] (channel)}
          <label
            class="cursor-pointer rounded-lg border border-line px-3 py-2 text-sm text-ink-2 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]"
          >
            <input type="checkbox" name="channels" value={channel} checked={value.channels.includes(channel as 'push' | 'email')} class="sr-only" />{label}
          </label>
        {/each}
      </div>
    </fieldset>
  </div>
  <div class="flex flex-col gap-2">
    {#each TOGGLES as [name, label] (name)}
      <label class="flex items-center gap-3 text-sm text-ink-2">
        <input type="checkbox" {name} checked={value[name]} class="h-4 w-4 accent-[var(--accent)]" />{label}
      </label>
    {/each}
  </div>
  <input type="hidden" name="timezone" value={timezone} />
  <p class="text-xs text-muted">Time zone: <span class="font-mono">{timezone || value.timezone}</span></p>
  <div><button type="submit" class="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save reminders'}</button></div>
</form>
