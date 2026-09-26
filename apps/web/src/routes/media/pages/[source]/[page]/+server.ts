import { isUuid } from '$lib/citations';
import { proxyImage } from '$lib/server/media';
import type { RequestHandler } from './$types';

// Full-resolution page render, streamed from the API as the signed-in user.
export const GET: RequestHandler = (event) => {
  const { source, page } = event.params;
  if (!isUuid(source) || !/^[1-9]\d{0,5}$/.test(page)) return new Response(null, { status: 404 });
  return proxyImage(event, `/v1/library/sources/${source}/pages/${page}/image`);
};
