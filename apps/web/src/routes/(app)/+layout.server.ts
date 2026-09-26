import { redirect } from '@sveltejs/kit';
import { authEnabled } from '$lib/server/auth';
import type { LayoutServerLoad } from './$types';

// Every page in the app group needs a session, except `/`, which renders the
// sign-in screen when there is none.
export const load: LayoutServerLoad = ({ locals, url }) => {
  if (!locals.user && url.pathname !== '/') redirect(303, '/');
  return { user: locals.user, authEnabled: authEnabled() };
};
