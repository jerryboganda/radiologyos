import { fail } from '@sveltejs/kit';
import { attempt, listQuestions } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const result = await listQuestions(event, 10);
  return {
    online: result.state === 'ok',
    questions: result.state === 'ok' ? result.data : [],
    detail: result.state === 'error' ? result.detail : null
  };
};

export const actions: Actions = {
  answer: async (event) => {
    const form = await event.request.formData();
    const questionId = String(form.get('question_id') ?? '');
    const choice = Number(form.get('choice'));
    if (!questionId || !Number.isInteger(choice) || choice < 0) {
      return fail(400, { questionId, error: 'Choose an option first.' });
    }
    const result = await attempt(event, questionId, choice);
    if (result.state !== 'ok') {
      return fail(503, { questionId, error: failureMessage(result, 'Answer checking is not online yet.') });
    }
    return { questionId, choice, result: result.data };
  }
};
