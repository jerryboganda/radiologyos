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

function toAutosave(value: unknown): AutosaveIn | null {
  if (!value || typeof value !== 'object') return null;
  const { revision, answers } = value as { revision?: unknown; answers?: unknown };
  if (!Number.isInteger(revision) || (revision as number) < 0) return null;
  if (!answers || typeof answers !== 'object' || Array.isArray(answers)) return null;
  const entries = Object.entries(answers as Record<string, unknown>);
  if (entries.length > 300) return null;
  const clean: AutosaveIn['answers'] = {};
  for (const [id, option] of entries) {
    if (!isUuid(id)) return null;
    if (option !== null && !(Number.isInteger(option) && (option as number) >= 0 && (option as number) <= 4)) return null;
    clean[id] = option as number | null;
  }
  return { revision: revision as number, answers: clean };
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
