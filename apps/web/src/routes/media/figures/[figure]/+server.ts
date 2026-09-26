import { isUuid } from '$lib/citations';
import { proxyImage } from '$lib/server/media';
import type { RequestHandler } from './$types';

// Figure crop at source resolution, streamed from the API as the signed-in user.
export const GET: RequestHandler = (event) => {
  const { figure } = event.params;
  if (!isUuid(figure)) return new Response(null, { status: 404 });
  return proxyImage(event, `/v1/library/figures/${figure}/image`);
};
