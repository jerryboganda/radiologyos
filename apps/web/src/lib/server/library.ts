// Library API client (live endpoints: apps/api/app/api/library.py).
import type { RequestEvent } from '@sveltejs/kit';
import type { ApiResult } from '$lib/api-state';
import { isProcessing } from '$lib/pipeline';
import type {
  ReaderPage,
  ReprocessResponse,
  SearchResponse,
  SourceDetail,
  SourceRow,
  SourceSummary
} from '$lib/types/library';
import { isRedList, isSummary } from '$lib/red-list';
import type { FactDecision, FileSummary, RedList, RedStatus, Verdict } from '$lib/types/red-list';
import { apiFetch } from './api';
import { getJson, query, sendJson } from './client';

const LIB = '/v1/library';
/** Cap per-load detail calls; the newest processing sources are shown first anyway. */
const MAX_DETAIL_CALLS = 8;

function mayStillRun(source: SourceSummary): boolean {
  if (isProcessing(source.status)) return true;
  return source.status === 'ready' && (source.page_count ?? 0) > source.pages_parsed;
}

/** Sources plus live step status for the ones that may still be processing. */
export async function listSources(event: RequestEvent): Promise<ApiResult<SourceRow[]>> {
  const result = await getJson<SourceSummary[]>(event, `${LIB}/sources`);
  if (result.state !== 'ok') return result;
  const candidates = new Set(result.data.filter(mayStillRun).slice(0, MAX_DETAIL_CALLS).map((s) => s.id));
  const rows = await Promise.all(
    result.data.map(async (source): Promise<SourceRow> => {
      if (!candidates.has(source.id)) return { ...source, steps: null };
      const detail = await sourceDetail(event, source.id);
      return { ...source, steps: detail.state === 'ok' ? detail.data.steps : null };
    })
  );
  return { state: 'ok', data: rows };
}

export function sourceDetail(event: RequestEvent, id: string) {
  return getJson<SourceDetail>(event, `${LIB}/sources/${id}`);
}

export function readPage(event: RequestEvent, id: string, page: number) {
  return getJson<ReaderPage>(event, `${LIB}/sources/${id}/pages/${page}`);
}

/** Owner-only re-run of one source's pipeline; unchanged text is never re-paid (ADR 0030). */
export function reprocessSource(event: RequestEvent, id: string) {
  return sendJson<ReprocessResponse>(event, `${LIB}/sources/${id}/reprocess`, 'POST');
}

export function deleteSource(event: RequestEvent, id: string) {
  return sendJson<void>(event, `${LIB}/sources/${id}`, 'DELETE');
}

export function searchLibrary(event: RequestEvent, query: string, limit = 12) {
  return sendJson<SearchResponse>(event, `${LIB}/search`, 'POST', { query, limit }, { timeoutMs: 30_000 });
}

/** Query for GET /v1/library/red-list. */
export interface RedListQuery {
  status?: RedStatus;
  sourceId?: string;
  limit?: number;
}

const BAD_SHAPE = { state: 'error', status: 502, detail: 'The review list came back in an unexpected shape.', kind: 'error' } as const;

/** The owner's red review list with its evidence (ADR 0038, ADR 0041), shape-checked. */
export async function getRedList(event: RequestEvent, q: RedListQuery = {}, timeoutMs?: number): Promise<ApiResult<RedList>> {
  const qs = query({ status: q.status, source_id: q.sourceId, limit: q.limit });
  const result = await getJson<unknown>(event, `${LIB}/red-list${qs}`, { timeoutMs });
  if (result.state !== 'ok') return result;
  return isRedList(result.data) ? { state: 'ok', data: result.data } : BAD_SHAPE;
}

/** Per-file open and reviewed counts, shape-checked. */
export async function getRedSummary(event: RequestEvent, timeoutMs?: number): Promise<ApiResult<FileSummary[]>> {
  const result = await getJson<unknown>(event, `${LIB}/red-list/summary`, { timeoutMs });
  if (result.state !== 'ok') return result;
  return isSummary(result.data) ? { state: 'ok', data: result.data } : BAD_SHAPE;
}

export function giveRedVerdict(event: RequestEvent, id: string, verdict: Verdict, note: string) {
  return sendJson<void>(event, `${LIB}/red-list/${id}/verdict`, 'POST', { verdict, note: note || null });
}

export function decideFlaggedFact(event: RequestEvent, id: string, decision: FactDecision, note: string) {
  return sendJson<void>(event, `${LIB}/red-list/claims/${id}`, 'POST', { decision, note: note || null });
}

/** Stream the owner's full red-list CSV through as the signed-in user. */
export async function exportRedList(event: RequestEvent): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await apiFetch(event, `${LIB}/red-list/export.csv`, { signal: AbortSignal.timeout(120_000) });
  } catch {
    return new Response('The API is unreachable.', { status: 502, headers: { 'cache-control': 'no-store' } });
  }
  if (!upstream.ok || !upstream.body) {
    await upstream.body?.cancel();
    const status = upstream.status === 401 || upstream.status === 403 ? upstream.status : 502;
    return new Response('The export could not be made.', { status, headers: { 'cache-control': 'no-store' } });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'text/csv; charset=utf-8',
      'content-disposition': upstream.headers.get('content-disposition') ?? 'attachment; filename="red-review-list.csv"',
      'cache-control': 'private, no-store',
      'x-content-type-options': 'nosniff'
    }
  });
}

/**
 * Stream a multipart upload straight through to the API without buffering the
 * file in the web server. The browser's content-type (with boundary) is kept.
 */
export async function forwardUpload(event: RequestEvent): Promise<Response> {
  const contentType = event.request.headers.get('content-type') ?? '';
  if (!contentType.startsWith('multipart/form-data') || !event.request.body) {
    return Response.json({ detail: 'multipart/form-data upload required' }, { status: 415 });
  }
  const init = {
    method: 'POST',
    headers: { 'content-type': contentType },
    body: event.request.body,
    duplex: 'half'
  } as RequestInit;
  let upstream: Response;
  try {
    upstream = await apiFetch(event, `${LIB}/sources`, init);
  } catch {
    return Response.json({ detail: 'The API is unreachable.' }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'application/json',
      'cache-control': 'no-store'
    }
  });
}
