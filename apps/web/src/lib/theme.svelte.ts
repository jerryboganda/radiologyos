// Client-side theme switching. The choice is stored in a plain display cookie
// (read by the head script in app.html and by hooks.server.ts), never a token.
import { resolveTheme, THEME_COLORS, themeCookie, type ThemePref } from './theme';

/** null until the user changes it in this tab; fall back to page.data.theme. */
export const themeState = $state<{ pref: ThemePref | null }>({ pref: null });

function systemDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function applyTheme(pref: ThemePref): void {
  const resolved = resolveTheme(pref, systemDark());
  const root = document.documentElement;
  root.classList.toggle('dark', resolved === 'dark');
  root.style.colorScheme = resolved;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[resolved]);
}

export function setTheme(pref: ThemePref): void {
  themeState.pref = pref;
  document.cookie = themeCookie(pref, location.protocol === 'https:');
  applyTheme(pref);
}

/** Follow OS changes while the preference is "system". Returns a disposer. */
export function watchSystemTheme(current: () => ThemePref): () => void {
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  const onChange = () => {
    if (current() === 'system') applyTheme('system');
  };
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}
