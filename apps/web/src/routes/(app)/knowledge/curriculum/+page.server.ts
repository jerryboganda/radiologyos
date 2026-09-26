import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { isCurriculumFilter, parseCurriculumDecisionForm } from '$lib/knowledge';
import { failureMessage } from '$lib/server/client';
import { decideCurriculum, getCurriculum } from '$lib/server/knowledge';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const exam = event.url.searchParams.get('exam');
  const filter = isCurriculumFilter(exam) ? exam : null;
  const result = await getCurriculum(event, filter);
  return { filter, curriculum: dataOr(result, null), problem: loadProblem(result) };
};

export const actions: Actions = {
  decide: async (event) => {
    const parsed = parseCurriculumDecisionForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await decideCurriculum(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result) });
    const verb = result.data.review_status === 'approved' ? 'Approved' : 'Rejected';
    return { message: `${verb} curriculum ${result.data.version}.` };
  }
};
