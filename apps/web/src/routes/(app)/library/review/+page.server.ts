import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { parseFactForm, parseReviewedForm } from '$lib/red-list';
import { failureMessage } from '$lib/server/client';
import { decideFlaggedFact, getRedList, markRedReviewed } from '$lib/server/library';
import type { Actions, PageServerLoad } from './$types';

// The owner's red review list (ADR 0038): everything below the quality bar,
// plus facts flagged as contradicting standard teaching.
export const load: PageServerLoad = async (event) => {
  event.depends('app:red-list');
  const result = await getRedList(event);
  return {
    list: dataOr(result, { items: [], flagged_facts: [] }),
    problem: loadProblem(result)
  };
};

function failed(status: number, section: 'items' | 'facts', id: string, error: string) {
  return fail(status, { section, id, error });
}

export const actions: Actions = {
  reviewed: async (event) => {
    const parsed = parseReviewedForm(await event.request.formData());
    if (!parsed.ok) return failed(400, 'items', '', parsed.error);
    const result = await markRedReviewed(event, parsed.value.id);
    if (result.state !== 'ok') {
      const status = result.state === 'error' ? result.status : 503;
      return failed(status, 'items', parsed.value.id, failureMessage(result));
    }
    return { section: 'items', message: 'Marked as reviewed.' };
  },
  decideFact: async (event) => {
    const parsed = parseFactForm(await event.request.formData());
    if (!parsed.ok) return failed(400, 'facts', '', parsed.error);
    const result = await decideFlaggedFact(event, parsed.value.id, parsed.value.decision);
    if (result.state !== 'ok') {
      const status = result.state === 'error' ? result.status : 503;
      return failed(status, 'facts', parsed.value.id, failureMessage(result));
    }
    const message = parsed.value.decision === 'keep' ? 'Kept as your source says.' : 'Fact rejected.';
    return { section: 'facts', message };
  }
};
