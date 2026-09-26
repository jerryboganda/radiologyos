import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { isWeightTarget, parseApproveForm, parseExtractForm } from '$lib/knowledge';
import { failureMessage, getJson } from '$lib/server/client';
import { approveTopicWeights, extractSource, listConcepts, listConflicts, listTopicWeights } from '$lib/server/knowledge';
import { resolveAction, trustAction } from '$lib/server/knowledge-actions';
import type { SourceSummary } from '$lib/types/library';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const q = event.url.searchParams.get('q')?.trim().slice(0, 200) || null;
  const rawTarget = event.url.searchParams.get('target');
  const target = isWeightTarget(rawTarget) ? rawTarget : null;
  const [concepts, conflicts, weights, sources] = await Promise.all([
    listConcepts(event, q),
    listConflicts(event, 'open'),
    listTopicWeights(event, target),
    getJson<SourceSummary[]>(event, '/v1/library/sources')
  ]);
  return {
    q,
    target,
    concepts: dataOr(concepts, []),
    conceptsProblem: loadProblem(concepts),
    conflicts: dataOr(conflicts, []),
    conflictsProblem: loadProblem(conflicts),
    weights: dataOr(weights, []),
    weightsProblem: loadProblem(weights),
    sources: dataOr(sources, [])
      .filter((s) => s.status === 'ready')
      .map((s) => ({ id: s.id, title: s.title }))
  };
};

export const actions: Actions = {
  resolve: resolveAction,
  trust: trustAction,
  approve: async (event) => {
    const parsed = parseApproveForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'weights', error: parsed.error });
    const result = await approveTopicWeights(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { section: 'weights', error: failureMessage(result) });
    return { section: 'weights', message: `Approved ${result.data.approved} weight${result.data.approved === 1 ? '' : 's'}.` };
  },
  extract: async (event) => {
    const parsed = parseExtractForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'extract', error: parsed.error });
    const result = await extractSource(event, parsed.value.sourceId, parsed.value.body);
    if (result.state !== 'ok') return fail(400, { section: 'extract', error: failureMessage(result) });
    return { section: 'extract', message: 'Extraction queued. Concepts, claims, and weights appear once the worker finishes.' };
  }
};
