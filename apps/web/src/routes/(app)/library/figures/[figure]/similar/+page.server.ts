import { error } from '@sveltejs/kit';
import { loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { getJson } from '$lib/server/client';
import type { FigureHit } from '$lib/types/library';
import type { PageServerLoad } from './$types';

// Figures nearest to one of the caller's own, by figure embedding (ADR 0025).
export const load: PageServerLoad = async (event) => {
  const { figure } = event.params;
  if (!isUuid(figure)) error(404, 'Figure not found');
  const similar = await getJson<FigureHit[]>(event, `/v1/library/figures/${figure}/similar?limit=12`);
  if (similar.state === 'error' && similar.status === 404) error(404, 'Figure not found');
  return {
    figureId: figure,
    problem: loadProblem(similar),
    figures: similar.state === 'ok' ? similar.data : []
  };
};
