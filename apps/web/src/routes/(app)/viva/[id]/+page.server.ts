import { error, fail } from '@sveltejs/kit';
import { failureText, isKind } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { failureMessage } from '$lib/server/client';
import { answerViva, endViva, getViva } from '$lib/server/viva';
import { vivaError } from '$lib/viva';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  if (!isUuid(event.params.id)) error(404, 'Session not found');
  event.depends('app:viva');
  const result = await getViva(event, event.params.id);
  if (result.state === 'ok') return { session: result.data };
  if (isKind(result, 'not_found')) error(404, 'Session not found');
  error(result.state === 'error' ? result.status : 503, failureText(result));
};

export const actions: Actions = {
  answer: async (event) => {
    const form = await event.request.formData();
    const turnNo = Number(form.get('turn_no'));
    const text = String(form.get('answer_text') ?? '').trim();
    if (!Number.isInteger(turnNo) || turnNo < 1 || turnNo > 40) return fail(400, { error: 'Unknown question.' });
    if (text.length < 1 || text.length > 8000) return fail(400, { error: 'Write an answer first (up to 8000 characters).' });
    const result = await answerViva(event, event.params.id, turnNo, text);
    if (result.state !== 'ok') return fail(400, { error: vivaError(failureMessage(result)), draft: text });
    return { answered: turnNo };
  },
  end: async (event) => {
    const result = await endViva(event, event.params.id);
    if (result.state !== 'ok') return fail(400, { error: vivaError(failureMessage(result)) });
    return { ended: true };
  }
};
