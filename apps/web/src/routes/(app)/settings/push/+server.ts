// Browser → web server → API proxy for Web Push (subscribe, unsubscribe, test).
// The browser never holds an API credential; apiFetch signs each call.
import { failureText, type ApiResult } from '$lib/api-state';
import { toEndpoint, toSubscriptionBody } from '$lib/push';
import { deletePushSubscription, savePushSubscription, sendTestPush } from '$lib/server/notifications';
import type { RequestHandler } from './$types';

function reply(result: ApiResult<unknown>, ok: unknown = { ok: true }): Response {
  if (result.state === 'ok') return Response.json(ok);
  if (result.state === 'signed_out') return Response.json({ detail: failureText(result) }, { status: 401 });
  if (result.state === 'offline') return Response.json({ detail: failureText(result) }, { status: 503 });
  // 503 here means the server has no VAPID keys: that is configuration, not AI.
  const detail = result.kind === 'unavailable' ? 'Push is not configured on this server yet.' : failureText(result);
  return Response.json({ detail }, { status: result.status });
}

async function readBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

// Register this device's push subscription, or (`?test`) send a test notification.
export const POST: RequestHandler = async (event) => {
  if (event.url.searchParams.has('test')) {
    const result = await sendTestPush(event);
    return reply(result, result.state === 'ok' ? result.data : null);
  }
  const body = toSubscriptionBody(await readBody(event.request), event.request.headers.get('user-agent'));
  if (!body) return Response.json({ detail: 'Invalid push subscription.' }, { status: 400 });
  return reply(await savePushSubscription(event, body));
};

export const DELETE: RequestHandler = async (event) => {
  const endpoint = toEndpoint(await readBody(event.request));
  if (!endpoint) return Response.json({ detail: 'Invalid push subscription.' }, { status: 400 });
  return reply(await deletePushSubscription(event, endpoint));
};
