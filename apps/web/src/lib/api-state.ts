// How the UI interprets an API response. Pure for node --test.
//
// Every area now calls a deployed endpoint, so "offline" (the "coming online"
// state) is reserved for genuine network failures: no response at all, or a
// proxy/gateway error without a FastAPI error body. Everything the API itself
// answers is classified into a `kind` the pages can render precisely.
export type FailureKind =
  | 'unavailable' // 503 from the API: model runtime / feature not configured
  | 'usage_limit' // 429, or 503 whose detail says the usage window is exhausted
  | 'model_failed' // 502 from the API: the model call failed, retry
  | 'conflict' // 409: onboarding required, stale revision, open exam …
  | 'not_found'
  | 'invalid' // 400 / 422
  | 'forbidden'
  | 'error';

export type ApiResult<T> =
  | { state: 'ok'; data: T }
  | { state: 'offline'; status: number }
  | { state: 'signed_out' }
  | { state: 'error'; status: number; detail: string; kind: FailureKind };

export type ApiFailure = Exclude<ApiResult<never>, { state: 'ok' }>;

const GATEWAY = new Set([502, 503, 504]);
const USAGE = /usage (limit|window)/i;

function kindOf(status: number, detail: string): FailureKind {
  if (status === 429) return 'usage_limit';
  if (status === 503) return USAGE.test(detail) ? 'usage_limit' : 'unavailable';
  if (status === 502) return 'model_failed';
  if (status === 409) return 'conflict';
  if (status === 404) return 'not_found';
  if (status === 400 || status === 422) return 'invalid';
  if (status === 403) return 'forbidden';
  return 'error';
}

/**
 * Classify a non-2xx status. `hasDetail` is false when the body was not a
 * FastAPI error (e.g. a reverse proxy's HTML 502): that is a network failure.
 */
export function classifyFailure(status: number, detail: string, hasDetail = true): ApiFailure {
  if (status === 0) return { state: 'offline', status };
  if (status === 401) return { state: 'signed_out' };
  if (GATEWAY.has(status) && !hasDetail) return { state: 'offline', status };
  return { state: 'error', status, detail, kind: kindOf(status, detail) };
}

/** Extract a short human message from a FastAPI-style error body; null if absent. */
export function bodyDetail(body: unknown): string | null {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail.slice(0, 300);
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === 'string') return first.msg.slice(0, 300);
    }
  }
  return null;
}

export function errorDetail(body: unknown, fallback: string): string {
  return bodyDetail(body) ?? fallback;
}

export const MESSAGES = {
  offline: 'Can’t reach the radbrain service right now. Check your connection and try again.',
  signed_out: 'Your session has expired. Sign in again.',
  unavailable: 'AI is not configured on this server yet, so this can’t run. Everything else keeps working.',
  usage_limit: 'The AI usage window has been reached. Try again later.',
  model_failed: 'The AI model call failed. Please try again.'
} as const;

/** A friendly, user-facing sentence for any failure. */
export function failureText(result: ApiFailure): string {
  if (result.state === 'offline') return MESSAGES.offline;
  if (result.state === 'signed_out') return MESSAGES.signed_out;
  if (result.kind === 'unavailable' || result.kind === 'usage_limit' || result.kind === 'model_failed') {
    return MESSAGES[result.kind];
  }
  return result.detail;
}

/** True when the same request may succeed if simply retried later. */
export function isRetryable(result: ApiFailure): boolean {
  if (result.state === 'offline') return true;
  return result.state === 'error' && (result.kind === 'model_failed' || result.kind === 'usage_limit');
}

export function isKind(result: ApiResult<unknown>, kind: FailureKind): boolean {
  return result.state === 'error' && result.kind === kind;
}

export function dataOr<T>(result: ApiResult<T>, fallback: T): T {
  return result.state === 'ok' ? result.data : fallback;
}

/** A serialisable page-load problem (null when the call succeeded). */
export interface LoadProblem {
  offline: boolean;
  message: string;
}

export function loadProblem(result: ApiResult<unknown>): LoadProblem | null {
  if (result.state === 'ok') return null;
  return { offline: result.state === 'offline', message: failureText(result) };
}
