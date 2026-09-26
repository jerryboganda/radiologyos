// Data-rights API client (apps/api/app/api/data_rights.py, ADR 0018).
import type { RequestEvent } from '@sveltejs/kit';
import type { DataJob } from '$lib/types/data-rights';
import { apiFetch } from './api';
import { getJson, sendJson } from './client';

/** 202: a new or the already-active export job. 409 while the account is being deleted. */
export const requestExport = (event: RequestEvent) => sendJson<DataJob>(event, '/v1/me/export', 'POST');

export const listExports = (event: RequestEvent) => getJson<DataJob[]>(event, '/v1/me/exports');

/** 202: the queued delete job. 422 unless the typed confirmation matches. */
export const deleteAccount = (event: RequestEvent, confirmation: string) =>
  sendJson<DataJob>(event, '/v1/me', 'DELETE', { confirmation });

/**
 * Stream the caller's export ZIP from the API to the browser unchanged. The
 * response is never cacheable; the API audits every download.
 */
export async function proxyExport(event: RequestEvent, id: string): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await apiFetch(event, `/v1/me/exports/${encodeURIComponent(id)}/download`, {
      signal: AbortSignal.timeout(10 * 60_000)
    });
  } catch {
    return new Response('Export service unreachable', { status: 502, headers: { 'cache-control': 'no-store' } });
  }
  if (!upstream.ok || !upstream.body) {
    await upstream.body?.cancel();
    const status = [401, 404].includes(upstream.status) ? upstream.status : 502;
    return new Response(status === 404 ? 'Export not found or expired' : null, {
      status,
      headers: { 'cache-control': 'no-store' }
    });
  }
  const headers = new Headers({
    'content-type': 'application/zip',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    'content-disposition': upstream.headers.get('content-disposition') ?? 'attachment; filename="radbrain-export.zip"'
  });
  const length = upstream.headers.get('content-length');
  if (length) headers.set('content-length', length);
  return new Response(upstream.body, { status: 200, headers });
}
