import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { parseReviewForm, reviewMessage } from '$lib/review';
import { recomputeStats, reviewQueue, reviewQuestion } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const drafts = await reviewQueue(event, 20);
  return { problem: loadProblem(drafts), drafts: dataOr(drafts, []) };
};

export const actions: Actions = {
  review: async (event) => {
    const form = await event.request.formData();
    const questionId = String(form.get('question_id') ?? '');
    if (!isUuid(questionId)) return fail(400, { questionId, error: 'Unknown question.' });
    // Edits send only changed fields, so compare against the stored draft.
    const queue = await reviewQueue(event, 100);
    const draft = queue.state === 'ok' ? queue.data.find((d) => d.id === questionId) : undefined;
    if (!draft) return fail(409, { questionId, error: 'This question is no longer a draft.' });
    const parsed = parseReviewForm(form, {
      stem: draft.stem,
      topic: draft.topic,
      explanation: draft.explanation,
      options: draft.options.map((o) => o.text),
      key: draft.key,
      model_answer: draft.model_answer
    });
    if (!parsed.ok) return fail(400, { questionId, error: parsed.error });
    const result = await reviewQuestion(event, questionId, parsed.value);
    if (result.state !== 'ok') {
      const error = result.state === 'error' ? reviewMessage(result.detail) : failureMessage(result);
      return fail(400, { questionId, error });
    }
    return { questionId, reviewed: result.data.action, status: result.data.status };
  },
  stats: async (event) => {
    const result = await recomputeStats(event);
    if (result.state !== 'ok') return fail(400, { statsError: failureMessage(result) });
    return { stats: { computed: result.data.computed, retired: result.data.retired.length } };
  }
};
