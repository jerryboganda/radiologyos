// Pure request-guard decisions for hooks.server.ts. No SvelteKit runtime imports,
// so `node --test` can exercise them directly.
import { themeClass, type ThemePref } from '../theme.ts';

// Page routes are guarded in (app)/+layout.server.ts (redirects serialise
// correctly for client navigations there). Media, upload, tutor-stream,
// export-download, and alert-ack endpoints refuse here; apiFetch also refuses
// without a session.
export const SESSION_ENDPOINTS: readonly string[] = [
  '/media/',
  '/library/upload',
  '/tutor/stream',
  '/settings/exports/',
  '/settings/alerts/'
];

/** True when the request must be refused with 401 because it has no session. */
export function requiresSession(pathname: string, hasUser: boolean): boolean {
  return !hasUser && SESSION_ENDPOINTS.some((prefix) => pathname.startsWith(prefix));
}

export const THEME_PLACEHOLDER = '%radbrain.themeclass%';

/** Fill the <html> class placeholder with the server-rendered theme class. */
export function applyThemeClass(html: string, pref: ThemePref): string {
  return html.replace(THEME_PLACEHOLDER, themeClass(pref));
}
