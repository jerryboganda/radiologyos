import { fail, redirect } from '@sveltejs/kit';
import { itemsText } from '$lib/blueprints';
import { parseExamForm } from '$lib/questions';
import { createExam, listBlueprints, listExams } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const [result, blueprintResult] = await Promise.all([listExams(event), listBlueprints(event)]);
  const blueprints =
    blueprintResult.state === 'ok'
      ? blueprintResult.data.map((b) => ({ id: b.id, title: b.title, approved: b.approved, summary: itemsText(b) }))
      : [];
  const exams =
    result.state === 'ok'
      ? result.data.map((exam) => ({
          id: exam.id,
          mode: exam.mode,
          status: exam.status,
          started_at: exam.started_at,
          questions: exam.question_count,
          percent: exam.score_percent,
          pending: exam.pending_grading ?? 0
        }))
      : [];
  return { exams, blueprints };
};

export const actions: Actions = {
  create: async (event) => {
    const parsed = parseExamForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await createExam(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result) });
    redirect(303, `/exams/${result.data.id}`);
  }
};
