import { redirect } from '@sveltejs/kit';
import { loadAdminBanner } from '$lib/server/admin';
import { authEnabled } from '$lib/server/auth';
import type { LayoutServerLoad } from './$types';

// Every page in the app group needs a session, except `/`, which renders the
// sign-in screen when there is none.
export const load: LayoutServerLoad = async (event) => {
  const { locals, url } = event;
  if (!locals.user && url.pathname !== '/') redirect(303, '/');
  // Admin-only budget banner: skipped for other roles, runs alongside the page's
  // own loads (none await parent()), short timeout, and null on any failure.
  const adminBanner = await loadAdminBanner(event);
  return { user: locals.user, authEnabled: authEnabled(), adminBanner };
};
