import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { parseDecisionForm } from '$lib/data-rights';
import { failureMessage } from '$lib/server/client';
import {
  decideMapping,
  listCurriculumSystems,
  listMappings,
  listMerges,
  listNodeCandidates
} from '$lib/server/knowledge';
import { mergeAction } from '$lib/server/knowledge-actions';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const [mappings, systems, nodes, pending, applied] = await Promise.all([
    listMappings(event, 'review'),
    listCurriculumSystems(event),
    listNodeCandidates(event),
    listMerges(event, 'review'),
    listMerges(event, 'applied')
  ]);
  return {
    mappings: dataOr(mappings, []),
    mappingsProblem: loadProblem(mappings),
    systems: dataOr(systems, []),
    nodes: dataOr(nodes, []),
    merges: dataOr(pending, []),
    mergesProblem: loadProblem(pending),
    applied: dataOr(applied, []).slice(0, 20)
  };
};

export const actions: Actions = {
  decide: async (event) => {
    const parsed = parseDecisionForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await decideMapping(event, parsed.value.mappingId, parsed.value.body);
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result), mappingId: parsed.value.mappingId });
    const { decision } = parsed.value.body;
    const verb = decision === 'reject' ? 'Rejected' : decision === 'code' ? `Re-coded to ${result.data.curriculum_code}` : 'Accepted';
    return { message: `${verb}: ${result.data.source_title}, p. ${result.data.page_from}.` };
  },
  // Resolver pairs: merge, keep separate, or undo an applied merge (ADR 0030).
  merge: mergeAction
};
