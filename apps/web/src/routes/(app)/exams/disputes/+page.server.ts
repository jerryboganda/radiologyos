import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { disputeMessage, parseResolveForm } from '$lib/exam-review';
import { failureMessage } from '$lib/server/client';
import { disputeQueue, resolveDispute } from '$lib/server/disputes';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const queue = await disputeQueue(event, 50);
  const forbidden = queue.state === 'error' && queue.status === 403;
  return { forbidden, problem: forbidden ? null : loadProblem(queue), disputes: dataOr(queue, []) };
};

export const actions: Actions = {
  resolve: async (event) => {
    const parsed = parseResolveForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const { id, ...body } = parsed.value;
    const result = await resolveDispute(event, id, body);
    if (result.state !== 'ok') {
      const error = result.state === 'error' ? disputeMessage(result.detail) : failureMessage(result);
      return fail(400, { error, disputeId: id });
    }
    return { resolved: result.data.dispute.status, disputeId: id, percent: result.data.exam_percent };
  }
};
