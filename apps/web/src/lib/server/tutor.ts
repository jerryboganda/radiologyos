// Tutor API client (apps/api/app/api/tutor.py).
import type { RequestEvent } from '@sveltejs/kit';
import { bodyDetail } from '$lib/api-state';
import type { AskRequest, AskResponse, ThreadDetail, ThreadSummary } from '$lib/types/tutor';
import { apiFetch, json } from './api';
import { getJson, sendJson } from './client';

// The stream stays open for the whole answer (source, web, and judge calls);
// the API sends a keep-alive comment every 15 s so idle proxies do not cut it.
const STREAM_TIMEOUT_MS = 900_000;

export const listThreads = (event: RequestEvent) => getJson<ThreadSummary[]>(event, '/v1/tutor/threads');

export const getThread = (event: RequestEvent, id: string) =>
  getJson<ThreadDetail>(event, `/v1/tutor/threads/${encodeURIComponent(id)}`);

/** Synchronous and model-backed: can take minutes (503 not configured, 429 usage, 502 retry). */
export const ask = (event: RequestEvent, body: AskRequest) =>
  sendJson<AskResponse>(event, '/v1/tutor/ask', 'POST', body, { timeoutMs: 300_000 });

/**
 * Stream a multipart image upload to POST /v1/tutor/images (ADR 0025). The API
 * sniffs, size-checks, and re-encodes it; its status and JSON body pass through.
 */
export async function uploadImage(event: RequestEvent): Promise<Response> {
  const contentType = event.request.headers.get('content-type') ?? '';
  if (!contentType.startsWith('multipart/form-data') || !event.request.body) {
    return json({ detail: 'multipart/form-data upload required' }, 415);
  }
  let upstream: Response;
  try {
    upstream = await apiFetch(event, '/v1/tutor/images', {
      method: 'POST',
      headers: { 'content-type': contentType },
      body: event.request.body,
      duplex: 'half'
    } as RequestInit);
  } catch {
    return json({ detail: 'The tutor service is unreachable.' }, 502);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { 'content-type': upstream.headers.get('content-type') ?? 'application/json', 'cache-control': 'no-store' }
  });
}

/**
 * Proxy the SSE progress stream untouched. Anything that is not an event
 * stream (auth failure, validation, proxy error) becomes a JSON error with
 * the upstream status, so the page can fall back to the JSON route.
 */
export async function askStream(event: RequestEvent, body: AskRequest): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await apiFetch(event, '/v1/tutor/ask/stream', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal: AbortSignal.any([event.request.signal, AbortSignal.timeout(STREAM_TIMEOUT_MS)])
    });
  } catch {
    return json({ detail: 'The tutor service is unreachable.' }, 502);
  }
  const type = upstream.headers.get('content-type') ?? '';
  if (!upstream.ok || !upstream.body || !type.startsWith('text/event-stream')) {
    let detail: string | null = null;
    try {
      detail = bodyDetail(await upstream.json());
    } catch {
      detail = null;
    }
    return json({ detail: detail ?? `Request failed (${upstream.status})` }, upstream.ok ? 502 : upstream.status);
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-store',
      'x-accel-buffering': 'no'
    }
  });
}
