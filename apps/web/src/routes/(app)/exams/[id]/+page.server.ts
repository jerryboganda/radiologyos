import { error } from '@sveltejs/kit';
import { failureText, isKind } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { getExam } from '$lib/server/assessment';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  if (!isUuid(event.params.id)) error(404, 'Exam not found');
  event.depends('app:exam');
  // Reading an exam whose deadline has passed grades it server-side.
  const result = await getExam(event, event.params.id);
  if (result.state === 'ok') return { exam: result.data };
  if (isKind(result, 'not_found')) error(404, 'Exam not found');
  error(result.state === 'error' ? result.status : 503, failureText(result));
};
