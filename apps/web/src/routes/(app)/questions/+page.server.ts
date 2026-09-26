import { fail } from '@sveltejs/kit';
import { dataOr, isKind, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { parseGenerateForm, questionFilters } from '$lib/questions';
import { attempt, generateQuestions, listQuestions } from '$lib/server/assessment';
import { failureMessage, getJson } from '$lib/server/client';
import type { AttemptIn } from '$lib/types/assessment';
import type { SourceSummary } from '$lib/types/library';
import type { Actions, PageServerLoad } from './$types';

const OPEN_EXAM = 'This question is part of an exam you have not submitted yet. Finish that exam first.';

export const load: PageServerLoad = async (event) => {
  const filters = questionFilters(event.url.searchParams);
  const [questions, sources] = await Promise.all([
    listQuestions(event, { ...filters, limit: 20 }),
    getJson<SourceSummary[]>(event, '/v1/library/sources')
  ]);
  return {
    filters,
    problem: loadProblem(questions),
    questions: dataOr(questions, []),
    sources: dataOr(sources, [])
      .filter((s) => s.status === 'ready')
      .map((s) => ({ id: s.id, title: s.title }))
  };
};

function attemptBody(form: FormData): AttemptIn | null {
  const choice = form.get('choice');
  if (choice !== null) {
    const selected = Number(choice);
    return Number.isInteger(selected) && selected >= 0 && selected <= 4 ? { selected_option: selected } : null;
  }
  const text = String(form.get('answer_text') ?? '').trim();
  return text.length >= 1 && text.length <= 8000 ? { answer_text: text } : null;
}

export const actions: Actions = {
  answer: async (event) => {
    const form = await event.request.formData();
    const questionId = String(form.get('question_id') ?? '');
    const body = attemptBody(form);
    if (!isUuid(questionId) || !body) return fail(400, { questionId, error: 'Choose an option or write an answer first.' });
    const result = await attempt(event, questionId, body);
    if (result.state !== 'ok') {
      const error = isKind(result, 'conflict') ? OPEN_EXAM : failureMessage(result);
      return fail(400, { questionId, error });
    }
    return { questionId, chosen: body.selected_option ?? null, result: result.data };
  },
  generate: async (event) => {
    const parsed = parseGenerateForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { generateError: parsed.error });
    const result = await generateQuestions(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { generateError: failureMessage(result) });
    const { created, rejected, excerpt_count } = result.data;
    return {
      generated: {
        created: created.length,
        drafts: created.filter((q) => q.status !== 'active').length,
        rejected: rejected.length,
        excerpts: excerpt_count
      }
    };
  }
};
