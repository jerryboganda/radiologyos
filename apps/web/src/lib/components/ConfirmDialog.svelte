<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    open = $bindable(false),
    title,
    confirmLabel = 'Confirm',
    danger = false,
    children,
    onconfirm
  }: {
    open?: boolean;
    title: string;
    confirmLabel?: string;
    danger?: boolean;
    children: Snippet;
    onconfirm: () => void;
  } = $props();

  const uid = $props.id();
  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  onclose={() => (open = false)}
  class="m-auto w-[min(28rem,calc(100%-2rem))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/50"
  aria-labelledby="{uid}-title"
>
  <div class="p-6">
    <h2 id="{uid}-title" class="text-xl font-semibold">{title}</h2>
    <div class="mt-2 text-sm leading-relaxed text-ink-2">{@render children()}</div>
    <div class="mt-6 flex justify-end gap-2">
      <button type="button" class="btn btn-ghost" onclick={() => (open = false)}>Cancel</button>
      <button
        type="button"
        class="btn {danger ? 'btn-danger' : 'btn-primary'}"
        onclick={() => {
          open = false;
          onconfirm();
        }}>{confirmLabel}</button
      >
    </div>
  </div>
</dialog>
