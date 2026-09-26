import { fail } from '@sveltejs/kit';
import { listExams, startExam } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  event.depends('app:exams');
  const result = await listExams(event);
  return {
    online: result.state === 'ok',
    exams: result.state === 'ok' ? result.data : [],
    detail: result.state === 'error' ? result.detail : null
  };
};

export const actions: Actions = {
  start: async (event) => {
    const examId = String((await event.request.formData()).get('exam_id') ?? '');
    if (!examId) return fail(400, { error: 'Unknown exam.' });
    const result = await startExam(event, examId);
    if (result.state !== 'ok') {
      return fail(503, { error: failureMessage(result, 'Mock exams are not online yet.') });
    }
    return { started: result.data };
  }
};
