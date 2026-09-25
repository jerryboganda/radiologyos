import type { RequestHandler } from './$types';
import { previewFetch } from '$lib/server/preview';

export const GET: RequestHandler = async (event) => {
  const resource = event.url.searchParams.get('resource') ?? 'sources';
  return previewFetch(event, resource);
};

export const POST: RequestHandler = async (event) => {
  const resource = event.url.searchParams.get('resource') ?? 'sources';
  const body = await event.request.text();
  return previewFetch(event, resource, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body
  });
};
