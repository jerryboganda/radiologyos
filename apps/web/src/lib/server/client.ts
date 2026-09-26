// Typed JSON calls over apiFetch (the only path to the API). Network failures
// and undeployed endpoints become `offline` so pages can degrade gracefully.
import type { RequestEvent } from '@sveltejs/kit';
import { classifyFailure, errorDetail, type ApiResult } from '$lib/api-state';
import { apiFetch } from './api';

export interface CallOptions {
  /** A 404 means "that record does not exist", not "endpoint not deployed". */
  notFoundIsError?: boolean;
  timeoutMs?: number;
}

export async function apiJson<T>(
  event: RequestEvent,
  path: string,
  init: RequestInit = {},
  options: CallOptions = {}
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await apiFetch(event, path, {
      ...init,
      signal: AbortSignal.timeout(options.timeoutMs ?? 15_000)
    });
  } catch {
    return { state: 'offline', status: 0 };
  }
  if (response.status === 204) return { state: 'ok', data: undefined as T };
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok) return { state: 'ok', data: body as T };
  const detail = errorDetail(body, `Request failed (${response.status})`);
  return classifyFailure(response.status, detail, options.notFoundIsError);
}

export function getJson<T>(event: RequestEvent, path: string, options?: CallOptions) {
  return apiJson<T>(event, path, {}, options);
}

export function sendJson<T>(
  event: RequestEvent,
  path: string,
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
  options?: CallOptions
) {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { 'content-type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  return apiJson<T>(event, path, init, options);
}

/** A form-action-friendly message for a failed mutation. */
export function failureMessage(result: ApiResult<unknown>, offline: string): string {
  switch (result.state) {
    case 'ok':
      return '';
    case 'offline':
      return offline;
    case 'signed_out':
      return 'Your session has expired. Sign in again.';
    case 'error':
      return result.detail;
  }
}
