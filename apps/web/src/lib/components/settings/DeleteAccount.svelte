<script lang="ts">
  import { enhance } from '$app/forms';
  import { confirmsDeletion } from '$lib/data-rights';
  import { DELETE_CONFIRMATION } from '$lib/types/data-rights';
  import Notice from '../Notice.svelte';

  let { error = null, queued = false }: { error?: string | null; queued?: boolean } = $props();
  const uid = $props.id();
  let typed = $state('');
  let busy = $state(false);
  let matches = $derived(confirmsDeletion(typed));
</script>

{#if queued}
  <Notice tone="ok">
    Deletion is under way. Your uploads, pages, figures, search index, cards, questions, tutor history, plans, exports, and sign-in
    are being erased; only a record that an account was deleted is kept. You can sign out now.
  </Notice>
  <form method="POST" action="/auth/logout" class="mt-4"><button class="btn btn-ghost" type="submit">Sign out</button></form>
{:else}
  <p class="mt-1 text-sm text-ink-2">
    Permanently erases your account and everything derived from it: uploaded files, page images and figures, text and embeddings,
    claims, cards and reviews, questions and attempts, tutor chats, study plans, reminders, and exports. This cannot be undone.
    Export your data first if you want a copy.
  </p>
  <p class="mt-2 text-xs text-muted">Sources under a legal hold are kept until the hold is lifted; everything else is erased.</p>
  <form
    method="POST"
    action="?/deleteAccount"
    class="mt-4 flex flex-col gap-3 sm:max-w-md"
    use:enhance={() => {
      busy = true;
      return async ({ update }) => {
        await update({ reset: false });
        busy = false;
      };
    }}
  >
    <label for="{uid}-confirm" class="text-sm text-ink">
      Type <span class="font-mono font-semibold">{DELETE_CONFIRMATION}</span> to confirm
    </label>
    <input
      id="{uid}-confirm"
      name="confirmation"
      bind:value={typed}
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
      class="field font-mono"
      aria-describedby={error ? `${uid}-error` : undefined}
    />
    <div><button class="btn btn-danger" type="submit" disabled={!matches || busy}>Delete my account</button></div>
  </form>
  {#if error}<div id="{uid}-error" class="mt-4"><Notice tone="danger">{error}</Notice></div>{/if}
{/if}
