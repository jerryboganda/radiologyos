// Authenticated image proxy. Bytes are streamed through untouched (no
// re-encoding or downscaling) and are only ever privately cacheable.
import type { RequestEvent } from '@sveltejs/kit';
import { apiFetch } from './api';

const ALLOWED_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

export async function proxyImage(event: RequestEvent, path: string): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await apiFetch(event, path);
  } catch {
    return new Response('Image service unreachable', { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    await upstream.body?.cancel();
    const status = upstream.status === 404 || upstream.status === 401 ? upstream.status : 502;
    return new Response(null, { status, headers: { 'cache-control': 'no-store' } });
  }
  const type = (upstream.headers.get('content-type') ?? '').split(';')[0]?.trim() ?? '';
  const headers = new Headers({
    'content-type': ALLOWED_TYPES.has(type) ? type : 'image/png',
    'cache-control': 'private, max-age=300',
    'x-content-type-options': 'nosniff',
    vary: 'cookie'
  });
  const length = upstream.headers.get('content-length');
  if (length) headers.set('content-length', length);
  return new Response(upstream.body, { status: 200, headers });
}
