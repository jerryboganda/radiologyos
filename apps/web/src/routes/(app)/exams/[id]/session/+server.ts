// Browser → web server → API proxy for the exam screen (autosave, reload,
// submit). The browser never holds an API credential; apiFetch signs the call.
import type { ApiResult } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { getExam, saveAnswers, submitExam } from '$lib/server/assessment';
import type { AutosaveIn } from '$lib/types/assessment';
import type { RequestHandler } from './$types';

function reply(result: ApiResult<unknown>): Response {
  if (result.state === 'ok') return Response.json(result.data);
  if (result.state === 'offline') return Response.json({ detail: 'network' }, { status: 503 });
  if (result.state === 'signed_out') return Response.json({ detail: 'Sign in again.' }, { status: 401 });
  // Pass the API's stable code through (e.g. `stale_revision`) so the client can react.
  return Response.json({ detail: result.detail }, { status: result.status });
}

const MAX_TEXT = 8000;

function entriesOf(value: unknown): [string, unknown][] | null {
  if (value === undefined) return [];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entries = Object.entries(value as Record<string, unknown>);
  return entries.length <= 300 && entries.every(([id]) => isUuid(id)) ? entries : null;
}

const isOption = (v: unknown) => v === null || (Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 4);
const isText = (v: unknown) => v === null || (typeof v === 'string' && v.length <= MAX_TEXT);

function toAutosave(value: unknown): AutosaveIn | null {
  if (!value || typeof value !== 'object') return null;
  const body = value as { revision?: unknown; answers?: unknown; text_answers?: unknown };
  if (!Number.isInteger(body.revision) || (body.revision as number) < 0) return null;
  const options = entriesOf(body.answers ?? {});
  const texts = entriesOf(body.text_answers);
  if (!options || !texts) return null;
  if (!options.every(([, v]) => isOption(v)) || !texts.every(([, v]) => isText(v))) return null;
  return {
    revision: body.revision as number,
    answers: Object.fromEntries(options) as AutosaveIn['answers'],
    text_answers: Object.fromEntries(texts) as NonNullable<AutosaveIn['text_answers']>
  };
}

const badId = () => Response.json({ detail: 'Unknown exam.' }, { status: 400 });

export const GET: RequestHandler = async (event) => {
  if (!isUuid(event.params.id)) return badId();
  return reply(await getExam(event, event.params.id));
};

export const PUT: RequestHandler = async (event) => {
  if (!isUuid(event.params.id)) return badId();
  const body = toAutosave(await event.request.json().catch(() => null));
  if (!body) return Response.json({ detail: 'invalid_answer' }, { status: 422 });
  return reply(await saveAnswers(event, event.params.id, body));
};

export const POST: RequestHandler = async (event) => {
  if (!isUuid(event.params.id)) return badId();
  return reply(await submitExam(event, event.params.id));
};
