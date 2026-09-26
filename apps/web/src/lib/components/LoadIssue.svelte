<script lang="ts">
  import type { LoadProblem } from '$lib/api-state';
  import ComingOnline from './ComingOnline.svelte';
  import Notice from './Notice.svelte';
  import type { IconName } from './icons';

  // Network failures keep the "coming online" panel; API answers render as a notice.
  let {
    problem,
    title,
    icon = 'signal',
    compact = false
  }: { problem: LoadProblem; title: string; icon?: IconName; compact?: boolean } = $props();
</script>

{#if problem.offline}
  <ComingOnline {title} description={problem.message} {icon} {compact} />
{:else}
  <Notice tone="warn">{problem.message}</Notice>
{/if}
