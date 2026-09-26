// Library API client (live endpoints: apps/api/app/api/library.py).
import type { RequestEvent } from '@sveltejs/kit';
import type { ApiResult } from '$lib/api-state';
import { isProcessing } from '$lib/pipeline';
import type {
  ReaderPage,
  SearchResponse,
  SourceDetail,
  SourceRow,
  SourceSummary
} from '$lib/types/library';
import { apiFetch } from './api';
import { getJson, sendJson } from './client';

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

export function deleteSource(event: RequestEvent, id: string) {
  return sendJson<void>(event, `${LIB}/sources/${id}`, 'DELETE');
}

export function searchLibrary(event: RequestEvent, query: string, limit = 12) {
  return sendJson<SearchResponse>(event, `${LIB}/search`, 'POST', { query, limit }, { timeoutMs: 30_000 });
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
