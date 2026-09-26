<script lang="ts">
  import { citationHref, citationLabel, safeWebUrl, webHost } from '$lib/citations';
  import type { Citation, WebCitation } from '$lib/types/citation';
  import Icon from './Icon.svelte';

  let { citation, web }: { citation?: Citation; web?: WebCitation } = $props();
  let webUrl = $derived(web ? safeWebUrl(web.url) : null);
</script>

{#if citation}
  <a
    href={citationHref(citation)}
    class="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-0.5 align-middle font-mono text-[0.6875rem] text-ink-2 no-underline hover:border-accent hover:text-accent"
    title="Open in reader: {citationLabel(citation)}"
  >
    <Icon name="file" size={12} />
    <span class="truncate">{citationLabel(citation)}</span>
  </a>
{:else if web && webUrl}
  <a
    href={webUrl}
    target="_blank"
    rel="noopener noreferrer nofollow"
    class="inline-flex max-w-full items-center gap-1.5 rounded-md border border-web/40 bg-web-soft px-2 py-0.5 align-middle font-mono text-[0.6875rem] text-web no-underline hover:underline"
    title={web.title ?? webUrl}
  >
    <Icon name="globe" size={12} />
    <span class="truncate">{webHost(webUrl)}</span>
    <Icon name="external" size={11} />
  </a>
{/if}
