// Form actions shared by /knowledge and /knowledge/{concept}.
import { fail, type RequestEvent } from '@sveltejs/kit';
import { parseResolveForm } from '$lib/knowledge';
import { failureMessage } from './client';
import { resolveConflict } from './knowledge';

export async function resolveAction(event: RequestEvent) {
  const parsed = parseResolveForm(await event.request.formData());
  if (!parsed.ok) return fail(400, { section: 'resolve', error: parsed.error });
  const result = await resolveConflict(event, parsed.value.conflictId, parsed.value.body);
  if (result.state !== 'ok') return fail(400, { section: 'resolve', error: failureMessage(result) });
  return { section: 'resolve', resolved: parsed.value.conflictId };
}
