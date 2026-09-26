import { forwardUpload } from '$lib/server/library';
import type { RequestHandler } from './$types';

// Browser → this endpoint → API, streamed (no whole-file buffering here).
// adapter-node caps request bodies with BODY_SIZE_LIMIT (set in the Dockerfile).
export const POST: RequestHandler = (event) => forwardUpload(event);
