<script lang="ts">
  let { current }: { current: 'bank' | 'review' } = $props();
  const TABS = [
    { id: 'bank', href: '/questions', label: 'Question bank' },
    { id: 'review', href: '/questions/review', label: 'Review drafts' }
  ] as const;
</script>

<nav aria-label="Questions sections" class="mb-6 flex gap-1 border-b border-line">
  {#each TABS as tab (tab.id)}
    <a
      href={tab.href}
      aria-current={tab.id === current ? 'page' : undefined}
      class="-mb-px border-b-2 px-3 py-2 text-sm {tab.id === current ? 'border-accent font-medium text-ink' : 'border-transparent text-ink-2 hover:text-ink'}"
    >
      {tab.label}
    </a>
  {/each}
</nav>
