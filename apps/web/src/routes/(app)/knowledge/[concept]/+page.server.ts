import { error, redirect } from '@sveltejs/kit';
import { dataOr, failureText, isKind, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { getConcept, getConceptFigures, getGraph, getNote } from '$lib/server/knowledge';
import { resolveAction, synthesizeAction, trustAction, verifyAction } from '$lib/server/knowledge-actions';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const id = event.params.concept;
  if (!isUuid(id)) error(404, 'Concept not found');
  const [result, note, graph, figures] = await Promise.all([
    getConcept(event, id),
    getNote(event, id),
    getGraph(event, id),
    getConceptFigures(event, id)
  ]);
  if (result.state === 'ok') {
    // A concept merged by the Resolver redirects to its survivor (ADR 0030).
    if (result.data.id !== id) redirect(308, `/knowledge/${result.data.id}`);
    return {
      concept: result.data,
      note: dataOr(note, null),
      noteProblem: loadProblem(note),
      graph: dataOr(graph, null),
      figures: dataOr(figures, [])
    };
  }
  if (isKind(result, 'not_found')) error(404, 'Concept not found');
  error(result.state === 'error' ? result.status : 503, failureText(result));
};

export const actions: Actions = {
  resolve: resolveAction,
  trust: trustAction,
  synthesize: synthesizeAction,
  verify: verifyAction
};
