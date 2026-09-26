// Browser → web server → API download of the caller's own export ZIP.
// Owner-only and audited by the API; the response is never cached.
import { isUuid } from '$lib/data-rights';
import { proxyExport } from '$lib/server/data-rights';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
  if (!event.locals.user) return new Response(null, { status: 401, headers: { 'cache-control': 'no-store' } });
  if (!isUuid(event.params.id)) return new Response(null, { status: 404, headers: { 'cache-control': 'no-store' } });
  return proxyExport(event, event.params.id);
};
