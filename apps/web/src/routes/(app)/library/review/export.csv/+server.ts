import { exportRedList } from '$lib/server/library';
import type { RequestHandler } from './$types';

// The owner's whole red review list as CSV (ADR 0041), streamed from the API.
export const GET: RequestHandler = (event) => exportRedList(event);
