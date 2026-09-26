import type { Handle } from '@sveltejs/kit';
import { readSession } from '$lib/server/auth';
import { applyThemeClass, requiresSession } from '$lib/server/guard';
import { parseThemePref, THEME_COOKIE } from '$lib/theme';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = await readSession(event.cookies);
  event.locals.theme = parseThemePref(event.cookies.get(THEME_COOKIE));

  if (requiresSession(event.url.pathname, Boolean(event.locals.user))) {
    return Response.json({ detail: 'sign in required' }, { status: 401 });
  }

  const theme = event.locals.theme;
  return resolve(event, {
    transformPageChunk: ({ html }) => applyThemeClass(html, theme)
  });
};
