import { fail } from '@sveltejs/kit';
import { failureMessage } from '$lib/server/client';
import { approveTopicWeight, listConcepts, listConflicts, listTopicWeights } from '$lib/server/knowledge';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const [concepts, conflicts, weights] = await Promise.all([
    listConcepts(event),
    listConflicts(event),
    listTopicWeights(event)
  ]);
  return {
    concepts: concepts.state === 'ok' ? concepts.data : null,
    conflicts: conflicts.state === 'ok' ? conflicts.data : null,
    weights: weights.state === 'ok' ? weights.data : null
  };
};

export const actions: Actions = {
  approve: async (event) => {
    const id = String((await event.request.formData()).get('weight_id') ?? '');
    if (!id) return fail(400, { error: 'Unknown topic weight.' });
    const result = await approveTopicWeight(event, id);
    if (result.state !== 'ok') {
      return fail(503, { error: failureMessage(result, 'Topic-weight approval is not online yet.') });
    }
    return { approved: id };
  }
};
