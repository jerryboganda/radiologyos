<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import { NOTE_MAX } from '$lib/red-list';
  import type { Verdict } from '$lib/types/red-list';

  // The owner's verdict and free-text note for one red-list entry (ADR 0041).
  let {
    id,
    verdict,
    note,
    error = '',
    message = ''
  }: { id: string; verdict: Verdict | null; note: string | null; error?: string; message?: string } = $props();

  const CHOICES: { value: Verdict; label: string; help: string; tone: string }[] = [
    { value: 'correct', label: 'Correct as it is', help: 'Keep it; nothing is wrong.', tone: 'has-checked:border-ok has-checked:bg-ok-soft' },
    { value: 'needs_fix', label: 'Needs fixing', help: 'Keep it, but it must be corrected.', tone: 'has-checked:border-warn has-checked:bg-warn-soft' },
    { value: 'remove', label: 'Remove it', help: 'It is wrong or useless.', tone: 'has-checked:border-danger has-checked:bg-danger-soft' }
  ];
  let busy = $state(false);
</script>

<form
  method="POST"
  action="?/verdict"
  class="mt-4 border-t border-danger/25 pt-4"
  use:enhance={() => {
    busy = true;
    return async ({ update }) => {
      await update({ reset: false });
      busy = false;
    };
  }}
>
  <input type="hidden" name="id" value={id} />
  <fieldset disabled={busy}>
    <legend class="mb-2 font-semibold text-ink">Your verdict</legend>
    <div class="grid gap-2 sm:grid-cols-3">
      {#each CHOICES as choice (choice.value)}
        <label class="flex min-h-14 cursor-pointer items-start gap-2 rounded-lg border-2 border-line bg-surface p-3 {choice.tone}">
          <input type="radio" name="verdict" value={choice.value} required checked={verdict === choice.value} class="mt-1 h-4 w-4 shrink-0" />
          <span class="min-w-0">
            <span class="block font-semibold text-ink">{choice.label}</span>
            <span class="block text-xs text-ink-2">{choice.help}</span>
          </span>
        </label>
      {/each}
    </div>
    <label for="note-{id}" class="mt-3 mb-1 block text-sm font-medium text-ink">Your note (optional)</label>
    <textarea id="note-{id}" name="note" rows="2" maxlength={NOTE_MAX} class="field text-sm" value={note ?? ''}></textarea>
    <div class="mt-2 flex flex-wrap items-center gap-3">
      <button class="btn btn-danger min-h-10 px-4 text-sm"><Icon name="check" size={14} /> {busy ? 'Saving…' : 'Save verdict'}</button>
      {#if error}<p class="text-sm font-medium text-danger" role="alert">{error}</p>{/if}
      {#if message && !error}<p class="text-sm font-medium text-ok" role="status">{message}</p>{/if}
    </div>
  </fieldset>
</form>
