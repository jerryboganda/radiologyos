// Form actions shared by /knowledge, /knowledge/{concept} and /knowledge/review.
import { fail, type RequestEvent } from '@sveltejs/kit';
import { parseMergeForm, parseResolveForm, parseTrustForm, parseVerifyForm } from '$lib/knowledge';
import { failureMessage } from './client';
import { decideMerge, resolveConflict, synthesizeNote, trustConflict, undoMerge, verifyNote } from './knowledge';

export async function resolveAction(event: RequestEvent) {
  const parsed = parseResolveForm(await event.request.formData());
  if (!parsed.ok) return fail(400, { section: 'resolve', error: parsed.error });
  const result = await resolveConflict(event, parsed.value.conflictId, parsed.value.body);
  if (result.state !== 'ok') return fail(400, { section: 'resolve', error: failureMessage(result) });
  return { section: 'resolve', resolved: parsed.value.conflictId };
}

const TRUSTED = { a: 'Source A is now the trusted claim.', b: 'Source B is now the trusted claim.', both: 'Both claims kept as valid in context.' };

export async function trustAction(event: RequestEvent) {
  const parsed = parseTrustForm(await event.request.formData());
  if (!parsed.ok) return fail(400, { section: 'resolve', error: parsed.error });
  const result = await trustConflict(event, parsed.value.conflictId, parsed.value.body);
  if (result.state !== 'ok') return fail(400, { section: 'resolve', error: failureMessage(result) });
  return { section: 'resolve', resolved: parsed.value.conflictId, message: TRUSTED[parsed.value.body.trust] };
}

export async function mergeAction(event: RequestEvent) {
  const parsed = parseMergeForm(await event.request.formData());
  if (!parsed.ok) return fail(400, { section: 'merge', error: parsed.error });
  const { mergeId, action } = parsed.value;
  const result = action === 'undo' ? await undoMerge(event, mergeId) : await decideMerge(event, mergeId, action);
  if (result.state !== 'ok') return fail(400, { section: 'merge', error: failureMessage(result) });
  const { a_name, b_name } = result.data;
  const verb = action === 'undo' ? 'Unmerged' : action === 'merge' ? 'Merged' : 'Kept separate';
  return { section: 'merge', message: `${verb}: ${a_name} and ${b_name}.` };
}

export async function synthesizeAction(event: RequestEvent) {
  const id = event.params.concept ?? '';
  const result = await synthesizeNote(event, id);
  if (result.state !== 'ok') return fail(400, { section: 'note', error: failureMessage(result) });
  return { section: 'note', message: 'The note is being written from your claims. Reload in a minute.' };
}

export async function verifyAction(event: RequestEvent) {
  const parsed = parseVerifyForm(await event.request.formData());
  if (!parsed.ok) return fail(400, { section: 'note', error: parsed.error });
  const result = await verifyNote(event, event.params.concept ?? '', parsed.value.noteId);
  if (result.state !== 'ok') return fail(400, { section: 'note', error: failureMessage(result) });
  return { section: 'note', message: 'Note marked verified.' };
}
