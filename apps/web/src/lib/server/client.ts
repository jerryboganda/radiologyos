// Typed JSON calls over apiFetch (the only path to the API). Only genuine
// network failures become `offline`; API answers are classified by kind.
import type { RequestEvent } from '@sveltejs/kit';
import { bodyDetail, classifyFailure, failureText, type ApiResult } from '$lib/api-state';
import { apiFetch } from './api';

export interface CallOptions {
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
  const detail = bodyDetail(body);
  return classifyFailure(response.status, detail ?? `Request failed (${response.status})`, detail !== null);
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

/** A form-action-friendly message for a failed mutation ('' when it succeeded). */
export function failureMessage(result: ApiResult<unknown>): string {
  return result.state === 'ok' ? '' : failureText(result);
}

/** Build a query string from defined, non-empty values. */
export function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}
