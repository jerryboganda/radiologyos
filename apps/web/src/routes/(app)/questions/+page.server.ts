import { fail, redirect } from '@sveltejs/kit';
import { dataOr, isKind, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { parseGenerateForm, questionFilters } from '$lib/questions';
import { attempt, generateQuestions, listQuestions } from '$lib/server/assessment';
import { failureMessage, getJson } from '$lib/server/client';
import type { AttemptIn } from '$lib/types/assessment';
import { isExamTarget } from '$lib/types/study';
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
  // "Quiz me" on a figure card (ADR 0025): one SBA with that figure as F1.
  figure: async (event) => {
    const form = await event.request.formData();
    const figureId = String(form.get('figure_id') ?? '');
    const target = form.get('exam_target');
    if (!isUuid(figureId)) return fail(400, { generateError: 'That figure could not be found.' });
    const result = await generateQuestions(event, {
      type: 'sba',
      exam_target: isExamTarget(target) ? target : 'fcps2_theory',
      count: 1,
      figure_id: figureId
    });
    if (result.state !== 'ok') return fail(400, { generateError: failureMessage(result) });
    if (result.data.created.length === 0) {
      return fail(400, { generateError: 'No question on that figure passed the checks; try again or pick another figure.' });
    }
    redirect(303, '/questions?type=sba');
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
        rejected: rejected.filter((r) => !r.duplicate_of).length,
        duplicates: rejected.filter((r) => r.duplicate_of).length,
        excerpts: excerpt_count
      }
    };
  }
};
