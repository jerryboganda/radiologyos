<script lang="ts">
  import { enhance } from '$app/forms';
  import { invalidate } from '$app/navigation';

  let {
    turnNo,
    label,
    draft = '',
    disabled = false
  }: { turnNo: number; label: string; draft?: string; disabled?: boolean } = $props();

  let text = $state('');
  let sending = $state(false);
  let box: HTMLTextAreaElement | undefined = $state();
  let formEl: HTMLFormElement | undefined = $state();

  // A new question gets an empty box (or the draft of a refused answer) and focus.
  $effect(() => {
    void turnNo;
    text = draft;
    box?.focus();
  });

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && text.trim()) {
      event.preventDefault();
      formEl?.requestSubmit();
    }
  }
</script>

<form
  bind:this={formEl}
  method="POST"
  action="?/answer"
  class="flex flex-col gap-2"
  use:enhance={() => {
    sending = true;
    return async ({ update }) => {
      await update({ reset: false, invalidateAll: false });
      await invalidate('app:viva');
      sending = false;
    };
  }}
>
  <input type="hidden" name="turn_no" value={turnNo} />
  <label class="block">
    <span class="label">{label}</span>
    <textarea
      bind:this={box}
      bind:value={text}
      name="answer_text"
      class="field mt-1.5 min-h-32 w-full leading-relaxed"
      maxlength="8000"
      required
      disabled={disabled || sending}
      onkeydown={onKey}
      aria-describedby="answer-help-{turnNo}"
    ></textarea>
  </label>
  <div class="flex flex-wrap items-center justify-between gap-2">
    <span id="answer-help-{turnNo}" class="font-mono text-xs text-muted">Ctrl+Enter sends · {text.length}/8000</span>
    <button class="btn btn-primary" type="submit" disabled={disabled || sending || !text.trim()}>
      {sending ? 'Sending…' : 'Answer'}
    </button>
  </div>
</form>
