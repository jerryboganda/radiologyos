// Tutor API client (planned: /v1/tutor/*).
import type { RequestEvent } from '@sveltejs/kit';
import type { TutorAnswer, TutorThread, TutorThreadDetail } from '$lib/types/tutor';
import { getJson, sendJson } from './client';

export const listThreads = (event: RequestEvent) => getJson<TutorThread[]>(event, '/v1/tutor/threads');

export const getThread = (event: RequestEvent, id: string) =>
  getJson<TutorThreadDetail>(event, `/v1/tutor/threads/${encodeURIComponent(id)}`);

export const ask = (
  event: RequestEvent,
  question: string,
  threadId: string | null,
  allowWeb: boolean
) =>
  sendJson<TutorAnswer>(
    event,
    '/v1/tutor/ask',
    'POST',
    { question, thread_id: threadId, allow_web: allowWeb },
    { timeoutMs: 120_000 }
  );
