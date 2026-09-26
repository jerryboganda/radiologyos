import { error } from '@sveltejs/kit';
import { isUuid } from '$lib/citations';
import { readPage, sourceDetail } from '$lib/server/library';
import { parsePage } from '$lib/viewer';
import type { PageServerLoad } from './$types';

// Only `?page=` is read here; `?block=` is handled client-side so selecting a
// block (and updating the shareable URL) does not refetch the page.
export const load: PageServerLoad = async (event) => {
  const { source } = event.params;
  if (!isUuid(source)) error(404, 'Source not found');
  event.depends('app:reader');
  const pageNo = parsePage(event.url.searchParams.get('page'));
  const [detail, page] = await Promise.all([sourceDetail(event, source), readPage(event, source, pageNo)]);
  if (detail.state === 'error' && detail.status === 404) error(404, 'Source not found');
  if (detail.state !== 'ok') error(503, 'The library API is unavailable. Try again shortly.');
  return {
    source: detail.data,
    pageNo,
    page: page.state === 'ok' ? page.data : null
  };
};
