import { toSubscriptionBody } from '$lib/push';
import { deletePushSubscription, savePushSubscription, sendTestPush } from '$lib/server/notifications';
import type { ApiResult } from '$lib/api-state';
import type { RequestHandler } from './$types';

function reply(result: ApiResult<unknown>): Response {
  if (result.state === 'ok') return Response.json({ ok: true });
  if (result.state === 'offline') return Response.json({ detail: 'Push notifications are not online yet.' }, { status: 503 });
  if (result.state === 'signed_out') return Response.json({ detail: 'Sign in again.' }, { status: 401 });
  return Response.json({ detail: result.detail }, { status: result.status });
}

async function readBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

// Register this device's push subscription with the API (browser → here → API).
export const POST: RequestHandler = async (event) => {
  if (event.url.searchParams.has('test')) return reply(await sendTestPush(event));
  const body = toSubscriptionBody(await readBody(event.request));
  if (!body) return Response.json({ detail: 'Invalid push subscription.' }, { status: 400 });
  return reply(await savePushSubscription(event, body));
};

export const DELETE: RequestHandler = async (event) => {
  const body = toSubscriptionBody(await readBody(event.request));
  if (!body) return Response.json({ detail: 'Invalid push subscription.' }, { status: 400 });
  return reply(await deletePushSubscription(event, body.endpoint));
};
