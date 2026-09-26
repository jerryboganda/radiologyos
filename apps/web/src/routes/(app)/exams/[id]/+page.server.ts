import { error, fail } from '@sveltejs/kit';
import { dataOr, failureText, isKind } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { disputeMessage, parseDisputeForm } from '$lib/exam-review';
import { getExam } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import { listDisputes, openDispute } from '$lib/server/disputes';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  if (!isUuid(event.params.id)) error(404, 'Exam not found');
  event.depends('app:exam');
  // Reading an exam whose deadline has passed grades it server-side.
  const result = await getExam(event, event.params.id);
  if (result.state === 'ok') {
    const disputes = result.data.result ? dataOr(await listDisputes(event, event.params.id), []) : [];
    return { exam: result.data, disputes };
  }
  if (isKind(result, 'not_found')) error(404, 'Exam not found');
  error(result.state === 'error' ? result.status : 503, failureText(result));
};

export const actions: Actions = {
  dispute: async (event) => {
    if (!isUuid(event.params.id)) return fail(404, { disputeError: 'Exam not found.' });
    const parsed = parseDisputeForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { disputeError: parsed.error });
    const result = await openDispute(event, event.params.id, parsed.value);
    if (result.state !== 'ok') {
      const message = result.state === 'error' ? disputeMessage(result.detail) : failureMessage(result);
      return fail(400, { disputeError: message, questionId: parsed.value.question_id });
    }
    return { disputed: result.data.id, questionId: parsed.value.question_id };
  }
};
