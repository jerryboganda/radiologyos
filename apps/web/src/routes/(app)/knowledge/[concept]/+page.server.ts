import { error } from '@sveltejs/kit';
import { failureText, isKind } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { getConcept } from '$lib/server/knowledge';
import { resolveAction } from '$lib/server/knowledge-actions';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  if (!isUuid(event.params.concept)) error(404, 'Concept not found');
  const result = await getConcept(event, event.params.concept);
  if (result.state === 'ok') return { concept: result.data };
  if (isKind(result, 'not_found')) error(404, 'Concept not found');
  error(result.state === 'error' ? result.status : 503, failureText(result));
};

export const actions: Actions = { resolve: resolveAction };
