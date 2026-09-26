// Backend-for-frontend: the browser never holds an API credential. The web
// server signs a short-lived assertion carrying only the OIDC subject; the API
// resolves tenant and role from the membership table (apps/api/app/security/internal.py).
import { env } from '$env/dynamic/private';
import type { RequestEvent } from '@sveltejs/kit';
import { ApiUnavailable, signAssertion } from './assertion';

export { ApiUnavailable };

/** Call the API as the signed-in user. `path` must start with /v1/. */
export async function apiFetch(
  event: RequestEvent,
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const user = event.locals.user;
  if (!user) return json({ detail: 'sign in required' }, 401);
  if (!path.startsWith('/v1/')) return json({ detail: 'invalid API path' }, 400);
  let assertion: string;
  try {
    assertion = await signAssertion(user.subject, env.WEB_API_SECRET);
  } catch {
    return json({ detail: 'API is not configured' }, 503);
  }
  const headers = new Headers(init.headers);
  headers.set('x-radbrain-assertion', assertion);
  headers.delete('authorization');
  return fetch(`${env.API_INTERNAL_URL ?? 'http://localhost:8000'}${path}`, { ...init, headers });
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}
