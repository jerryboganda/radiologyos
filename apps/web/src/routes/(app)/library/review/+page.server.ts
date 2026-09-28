import { dataOr, loadProblem } from '$lib/api-state';
import { getRedSummary } from '$lib/server/library';
import type { PageServerLoad } from './$types';

// The owner's red review list (ADR 0038, ADR 0041): one card per file; each
// file's evidence and verdicts live on /library/review/[source].
export const load: PageServerLoad = async (event) => {
  event.depends('app:red-list');
  const result = await getRedSummary(event);
  return { files: dataOr(result, []), problem: loadProblem(result) };
};
