import { fail, redirect } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { failureMessage } from '$lib/server/client';
import { createViva, listVivas } from '$lib/server/viva';
import { parseStartForm, vivaError } from '$lib/viva';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const result = await listVivas(event);
  const params = event.url.searchParams;
  const id = (name: string) => {
    const value = params.get(name);
    return value && isUuid(value) ? value : null;
  };
  return {
    problem: loadProblem(result),
    sessions: dataOr(result, []),
    // Prefill from "Viva on this figure" / "Practise as a staged case" links.
    prefill: {
      kind: params.get('kind') === 'image_case' ? ('image_case' as const) : ('viva' as const),
      figure_id: id('figure'),
      question_id: id('question'),
      topic: (params.get('topic') ?? '').slice(0, 200)
    }
  };
};

export const actions: Actions = {
  start: async (event) => {
    const parsed = parseStartForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { error: parsed.error });
    const result = await createViva(event, parsed.value);
    if (result.state !== 'ok') return fail(400, { error: vivaError(failureMessage(result)) });
    redirect(303, `/viva/${result.data.id}`);
  }
};
