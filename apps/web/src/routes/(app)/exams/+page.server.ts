import { fail, redirect } from '@sveltejs/kit';
import { parseExamForm } from '$lib/questions';
import { createExam, listExams } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const result = await listExams(event);
  const exams =
    result.state === 'ok'
      ? result.data.map((exam) => ({
          id: exam.id,
          mode: exam.mode,
          status: exam.status,
          started_at: exam.started_at,
          questions: exam.question_count,
          percent: exam.score_percent
        }))
      : [];
  return { exams };
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
