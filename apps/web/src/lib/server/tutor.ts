// Tutor API client (apps/api/app/api/tutor.py).
import type { RequestEvent } from '@sveltejs/kit';
import type { AskRequest, AskResponse, ThreadDetail, ThreadSummary } from '$lib/types/tutor';
import { getJson, sendJson } from './client';

export const listThreads = (event: RequestEvent) => getJson<ThreadSummary[]>(event, '/v1/tutor/threads');

export const getThread = (event: RequestEvent, id: string) =>
  getJson<ThreadDetail>(event, `/v1/tutor/threads/${encodeURIComponent(id)}`);

/** Synchronous and model-backed: can take minutes (503 not configured, 429 usage, 502 retry). */
export const ask = (event: RequestEvent, body: AskRequest) =>
  sendJson<AskResponse>(event, '/v1/tutor/ask', 'POST', body, { timeoutMs: 300_000 });
