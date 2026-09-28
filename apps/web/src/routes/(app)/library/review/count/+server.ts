import { json } from '@sveltejs/kit';
import { summaryCount } from '$lib/red-list';
import { getRedSummary } from '$lib/server/library';
import type { RequestHandler } from './$types';

// How many red-list entries wait for the owner (ADR 0038), summed from the
// per-file summary. Fetched once by the Library page, outside its polling load;
// any failure reads as 0.
export const GET: RequestHandler = async (event) => {
  const result = await getRedSummary(event, 5_000);
  const count = result.state === 'ok' ? summaryCount(result.data) : 0;
  return json({ count }, { headers: { 'cache-control': 'private, no-store' } });
};
