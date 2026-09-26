import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { parseBlueprintOverrideForm } from '$lib/blueprints';
import { approveBlueprint, listBlueprints, overrideBlueprint } from '$lib/server/assessment';
import { failureMessage } from '$lib/server/client';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const result = await listBlueprints(event);
  return { blueprints: dataOr(result, []), problem: loadProblem(result) };
};

export const actions: Actions = {
  override: async (event) => {
    const parsed = parseBlueprintOverrideForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await overrideBlueprint(event, parsed.value.id, { overrides: parsed.value.overrides });
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result), id: parsed.value.id });
    return { message: `Saved ${result.data.title}. Review it and approve again.` };
  },
  approve: async (event) => {
    const data = await event.request.formData();
    const id = String(data.get('blueprint_id') ?? '');
    const hash = String(data.get('content_hash') ?? '');
    if (!/^[a-z0-9_]{1,60}$/.test(id) || !/^[0-9a-f]{64}$/.test(hash)) return fail(400, { error: 'Reload the page and try again.' });
    const result = await approveBlueprint(event, id, hash);
    if (result.state !== 'ok') return fail(400, { error: failureMessage(result), id });
    return { message: `Approved ${result.data.title}.` };
  }
};
