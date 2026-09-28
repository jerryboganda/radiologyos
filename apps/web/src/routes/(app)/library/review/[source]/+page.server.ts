import { error, fail } from '@sveltejs/kit';
import { dataOr, loadProblem, type ApiResult } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { parseFactForm, parseStatus, parseVerdictForm, sortByPage, verdictText } from '$lib/red-list';
import { failureMessage } from '$lib/server/client';
import { decideFlaggedFact, getRedList, getRedSummary, giveRedVerdict } from '$lib/server/library';
import type { Actions, PageServerLoad } from './$types';

// One file's red-list entries with their evidence (ADR 0038, ADR 0041). The
// owner records a verdict and a note per entry; changing their mind is allowed.
const LIMIT = 2000;

export const load: PageServerLoad = async (event) => {
  event.depends('app:red-list');
  const { source } = event.params;
  if (!isUuid(source)) error(404, 'Source not found');
  const status = parseStatus(event.url.searchParams.get('status'));
  const [summary, list] = await Promise.all([
    getRedSummary(event),
    getRedList(event, { status, sourceId: source, limit: LIMIT })
  ]);
  const data = dataOr(list, { items: [], flagged_facts: [] });
  const file = dataOr(summary, []).find((f) => f.source_id === source) ?? null;
  return {
    sourceId: source,
    status,
    file,
    items: sortByPage(data.items),
    facts: data.flagged_facts,
    problem: loadProblem(list)
  };
};

type Section = 'items' | 'facts';

function refused(result: ApiResult<unknown>, section: Section, id: string) {
  const status = result.state === 'error' ? result.status : 503;
  return fail(status, { section, id, error: failureMessage(result) });
}

export const actions: Actions = {
  verdict: async (event) => {
    const parsed = parseVerdictForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'items' as Section, id: '', error: parsed.error });
    const { id, verdict, note } = parsed.value;
    const result = await giveRedVerdict(event, id, verdict, note);
    if (result.state !== 'ok') return refused(result, 'items', id);
    return { section: 'items' as Section, id, message: `Saved: ${verdictText(verdict)}.` };
  },
  decideFact: async (event) => {
    const parsed = parseFactForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'facts' as Section, id: '', error: parsed.error });
    const { id, decision, note } = parsed.value;
    const result = await decideFlaggedFact(event, id, decision, note);
    if (result.state !== 'ok') return refused(result, 'facts', id);
    const message = decision === 'keep' ? 'Saved: kept as your source says.' : 'Saved: fact rejected.';
    return { section: 'facts' as Section, id, message };
  }
};
