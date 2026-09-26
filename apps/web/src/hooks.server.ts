import type { Handle } from '@sveltejs/kit';
import { readSession } from '$lib/server/auth';
import { parseThemePref, THEME_COOKIE, themeClass } from '$lib/theme';

// Page routes are guarded in (app)/+layout.server.ts (redirects serialise
// correctly for client navigations there). Media and upload endpoints refuse
// here; apiFetch also refuses without a session.
const ENDPOINTS = ['/media/', '/library/upload'];

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = await readSession(event.cookies);
  event.locals.theme = parseThemePref(event.cookies.get(THEME_COOKIE));

  if (!event.locals.user && ENDPOINTS.some((p) => event.url.pathname.startsWith(p))) {
    return Response.json({ detail: 'sign in required' }, { status: 401 });
  }

  const htmlClass = themeClass(event.locals.theme);
  return resolve(event, {
    transformPageChunk: ({ html }) => html.replace('%radbrain.themeclass%', htmlClass)
  });
};
