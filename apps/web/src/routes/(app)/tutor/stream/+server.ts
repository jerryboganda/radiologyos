import { json } from '@sveltejs/kit';
import { askStream } from '$lib/server/tutor';
import { validateAsk } from '$lib/tutor-stream';
import type { RequestHandler } from './$types';

// Same-origin JSON POST → SSE progress for one tutor question (ADR 0013 v2).
// The browser never talks to the API directly; apiFetch signs as the user.
export const POST: RequestHandler = async (event) => {
  const origin = event.request.headers.get('origin');
  if (origin !== null && origin !== event.url.origin) {
    return json({ detail: 'Cross-origin request refused.' }, { status: 403 });
  }
  let payload: Record<string, unknown>;
  try {
    const parsed: unknown = await event.request.json();
    payload = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
  } catch {
    return json({ detail: 'Invalid request body.' }, { status: 400 });
  }
  const input = validateAsk(payload.question, payload.thread_id, payload.allow_web);
  if (!input.ok) return json({ detail: input.error }, { status: 400 });
  return askStream(event, input.body);
};
