import { searchLibrary } from '$lib/server/library';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const query = (event.url.searchParams.get('q') ?? '').trim().slice(0, 500);
  if (query.length < 2) return { query, result: null, state: 'idle' as const, detail: null };
  const result = await searchLibrary(event, query);
  return {
    query,
    result: result.state === 'ok' ? result.data : null,
    state: result.state,
    detail: result.state === 'error' ? result.detail : null
  };
};
