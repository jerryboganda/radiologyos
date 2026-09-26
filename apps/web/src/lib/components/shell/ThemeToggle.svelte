<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';
  import { nextThemePref, parseThemePref, THEME_PREFS, type ThemePref } from '$lib/theme';
  import { setTheme, themeState } from '$lib/theme.svelte';

  let { variant = 'cycle' }: { variant?: 'cycle' | 'segmented' } = $props();

  const LABELS: Record<ThemePref, string> = { light: 'Light', dark: 'Dark', system: 'System' };
  const ICON = { light: 'sun', dark: 'moon', system: 'system' } as const;

  let pref = $derived(themeState.pref ?? parseThemePref(page.data.theme as string | undefined));
</script>

{#if variant === 'cycle'}
  <button
    type="button"
    class="inline-flex h-10 w-10 items-center justify-center rounded-lg text-ink-2 hover:bg-surface-2 hover:text-ink"
    onclick={() => setTheme(nextThemePref(pref))}
    title="Theme: {LABELS[pref]} (click to change)"
    aria-label="Theme: {LABELS[pref]}. Switch to {LABELS[nextThemePref(pref)]}."
  >
    <Icon name={ICON[pref]} />
  </button>
{:else}
  <div role="radiogroup" aria-label="Colour theme" class="inline-flex rounded-xl border border-line bg-surface-2 p-1">
    {#each THEME_PREFS as option (option)}
      <button
        type="button"
        role="radio"
        aria-checked={pref === option}
        class="inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium
          {pref === option ? 'bg-surface text-ink shadow-sm ring-1 ring-line' : 'text-muted hover:text-ink'}"
        onclick={() => setTheme(option)}
      >
        <Icon name={ICON[option]} size={16} />
        {LABELS[option]}
      </button>
    {/each}
  </div>
{/if}
