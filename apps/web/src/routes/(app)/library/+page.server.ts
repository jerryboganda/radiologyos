import { fail } from '@sveltejs/kit';
import { isUuid } from '$lib/citations';
import { failureMessage } from '$lib/server/client';
import { deleteSource, listSources } from '$lib/server/library';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  event.depends('app:library');
  const result = await listSources(event);
  return {
    sources: result.state === 'ok' ? result.data : [],
    state: result.state,
    detail: result.state === 'error' ? result.detail : null
  };
};

export const actions: Actions = {
  delete: async (event) => {
    const id = String((await event.request.formData()).get('id') ?? '');
    if (!isUuid(id)) return fail(400, { error: 'Unknown source.' });
    const result = await deleteSource(event, id);
    if (result.state !== 'ok') {
      return fail(result.state === 'error' ? result.status : 503, {
        error: failureMessage(result, 'The library API is unavailable; nothing was deleted.')
      });
    }
    return { deleted: id };
  }
};
