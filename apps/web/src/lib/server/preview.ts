import { env } from '$env/dynamic/private';
import type { RequestEvent } from '@sveltejs/kit';
import { previewUserId } from './preview-identity';

export async function previewFetch(
  event: RequestEvent,
  resource: string,
  init: RequestInit = {}
): Promise<Response> {
  const user = event.locals.user;
  if (!user || env.PREVIEW_ENABLED !== 'true') {
    return new Response(JSON.stringify({ detail: 'preview unavailable' }), { status: 404 });
  }
  const routes: Record<string, string> = {
    sources: '/v1/preview/sources',
    search: '/v1/preview/search',
    plan: '/v1/preview/plan',
    onboarding: '/v1/preview/onboarding',
    today: '/v1/preview/today',
    cards: '/v1/preview/cards/due',
    questions: '/v1/preview/questions',
    tutor: '/v1/preview/tutor/ask',
    markdown: '/v1/preview/export/markdown',
    capabilities: '/v1/preview/capabilities',
    audit: '/v1/preview/release-audit'
  };
  const path = routes[resource];
  if (!path) return new Response(JSON.stringify({ detail: 'unknown preview resource' }), { status: 404 });
  const headers = new Headers(init.headers);
  headers.set('x-user-id', previewUserId(user.subject));
  headers.set('x-tenant-id', user.tenantId);
  headers.set('x-role', user.tenantRole);
  return fetch(`${env.API_INTERNAL_URL ?? 'http://localhost:8000'}${path}`, {
    ...init,
    headers
  });
}
