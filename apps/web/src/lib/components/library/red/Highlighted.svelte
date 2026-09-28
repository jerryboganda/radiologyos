<script lang="ts">
  import { highlight } from '$lib/red-list';

  // Evidence text with the given spans marked; plain text only (no {@html}).
  let { text, spans = [], class: className = '' }: { text: string; spans?: string[]; class?: string } = $props();
  let segments = $derived(highlight(text, spans));
</script>

<p class="whitespace-pre-wrap break-words {className}">{#each segments as segment, i (i)}{#if segment.mark}<mark class="rounded-sm bg-warn-soft px-0.5 font-medium text-ink ring-1 ring-warn/50">{segment.text}</mark>{:else}{segment.text}{/if}{/each}</p>
