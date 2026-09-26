<script lang="ts">
  import { citationLink } from '$lib/citations';
  import type { LooseCitation } from '$lib/types/citation';
  import Icon from './Icon.svelte';

  let { citation }: { citation: LooseCitation | null | undefined } = $props();
  let link = $derived(citationLink(citation));
</script>

{#if link?.kind === 'source'}
  <a
    href={link.href}
    class="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-0.5 align-middle font-mono text-[0.6875rem] text-ink-2 no-underline hover:border-accent hover:text-accent"
    title="Open in reader: {link.label}"
  >
    <Icon name="file" size={12} />
    <span class="truncate">{link.label}</span>
  </a>
{:else if link?.kind === 'web'}
  <a
    href={link.href}
    target="_blank"
    rel="noopener noreferrer nofollow"
    class="inline-flex max-w-full items-center gap-1.5 rounded-md border border-web/40 bg-web-soft px-2 py-0.5 align-middle font-mono text-[0.6875rem] text-web no-underline hover:underline"
    title={link.href}
  >
    <Icon name="globe" size={12} />
    <span class="truncate">{link.label}</span>
    <Icon name="external" size={11} />
  </a>
{/if}
