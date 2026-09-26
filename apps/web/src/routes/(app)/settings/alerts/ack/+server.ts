// Browser → web server → API: acknowledge embedding-budget alerts (admin banner
// and Settings). Script callers ask for JSON; a plain form post (no JS) is sent
// back to the page it came from. The API enforces org_admin / superadmin.
import { redirect } from '@sveltejs/kit';
import { failureText, isKind, type ApiFailure, type ApiResult } from '$lib/api-state';
import { parseAckIds, safeReturnPath } from '$lib/admin-usage';
import { acknowledgeAlert } from '$lib/server/admin';
import type { RequestHandler } from './$types';

function statusOf(failure: ApiFailure): number {
  if (failure.state === 'signed_out') return 401;
  if (failure.state === 'offline') return 503;
  return failure.status;
}

// 404 means the alert is already gone: acknowledging is idempotent.
const failed = (result: ApiResult<void>): result is ApiFailure => result.state !== 'ok' && !isKind(result, 'not_found');

export const POST: RequestHandler = async (event) => {
  const wantsJson = (event.request.headers.get('accept') ?? '').includes('application/json');
  const form = await event.request.formData().catch(() => null);
  const ids = form ? parseAckIds(form) : null;
  if (!ids) return Response.json({ detail: 'Unknown alert.' }, { status: 400 });
  const failure = (await Promise.all(ids.map((id) => acknowledgeAlert(event, id)))).find(failed);
  if (!wantsJson) redirect(303, safeReturnPath(form?.get('next')));
  if (!failure) return new Response(null, { status: 204 });
  return Response.json({ detail: failureText(failure) }, { status: statusOf(failure) });
};
