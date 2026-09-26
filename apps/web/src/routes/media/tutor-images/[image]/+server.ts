import { isUuid } from '$lib/citations';
import { proxyImage } from '$lib/server/media';
import type { RequestHandler } from './$types';

// An image the signed-in user attached to a tutor question, streamed from the
// API as that user; only its owner can read it (ADR 0025).
export const GET: RequestHandler = (event) => {
  const { image } = event.params;
  if (!isUuid(image)) return new Response(null, { status: 404 });
  return proxyImage(event, `/v1/tutor/images/${image}`);
};
