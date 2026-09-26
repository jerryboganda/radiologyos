<script lang="ts">
  // A visible keyboard-shortcut hint. Decorative: the control itself carries
  // aria-keyshortcuts, so screen readers are not told twice.
  let { key, class: extra = '' }: { key: string; class?: string } = $props();
</script>

<kbd
  aria-hidden="true"
  class="inline-flex min-w-[1.25rem] items-center justify-center rounded border border-line-strong bg-surface-2 px-1 font-mono text-[0.625rem] leading-4 text-muted {extra}"
  >{key}</kbd
>
