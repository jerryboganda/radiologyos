import { json } from '@sveltejs/kit';
import { uploadImage } from '$lib/server/tutor';
import type { RequestHandler } from './$types';

// Same-origin multipart upload of a tutor image → POST /v1/tutor/images (ADR 0025).
// Streamed through (no buffering here); the API validates type and size.
export const POST: RequestHandler = (event) => {
  const origin = event.request.headers.get('origin');
  if (origin !== null && origin !== event.url.origin) {
    return json({ detail: 'Cross-origin request refused.' }, { status: 403 });
  }
  return uploadImage(event);
};
