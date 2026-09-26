// Theme preference helpers. Pure (no DOM, no SvelteKit) so node --test can run them.
export type ThemePref = 'light' | 'dark' | 'system';

export const THEME_COOKIE = 'radbrain_theme';
export const THEME_PREFS: readonly ThemePref[] = ['light', 'dark', 'system'];
export const THEME_COLORS = { light: '#f5f3ee', dark: '#0b0e11' } as const;

export function parseThemePref(value: string | null | undefined): ThemePref {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system';
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): 'light' | 'dark' {
  if (pref === 'system') return systemDark ? 'dark' : 'light';
  return pref;
}

/** Cycle order used by the compact top-bar toggle. */
export function nextThemePref(pref: ThemePref): ThemePref {
  return pref === 'system' ? 'light' : pref === 'light' ? 'dark' : 'system';
}

/** Server-rendered class for <html>: explicit choices render correctly without JS. */
export function themeClass(pref: ThemePref): string {
  return pref === 'dark' ? 'dark' : '';
}

/** A display preference only (never a credential); one year, lax, whole site. */
export function themeCookie(pref: ThemePref, secure: boolean): string {
  const parts = [`${THEME_COOKIE}=${pref}`, 'Path=/', 'Max-Age=31536000', 'SameSite=Lax'];
  if (secure) parts.push('Secure');
  return parts.join('; ');
}
