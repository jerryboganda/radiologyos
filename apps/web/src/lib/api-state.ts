// How the UI interprets an API response. Pure for node --test.
//
// Several areas (tutor, study, questions, knowledge, notifications) call
// endpoints that are planned but may not be deployed yet. Those must degrade to
// a "coming online" state instead of an error page.
export type ApiResult<T> =
  | { state: 'ok'; data: T }
  | { state: 'offline'; status: number }
  | { state: 'signed_out' }
  | { state: 'error'; status: number; detail: string };

export type ApiFailure = Exclude<ApiResult<never>, { state: 'ok' }>;

const OFFLINE = new Set([0, 404, 405, 501, 502, 503, 504]);

/** Classify a non-2xx status. `notFoundIsError` for real resources (a missing source). */
export function classifyFailure(status: number, detail: string, notFoundIsError = false): ApiFailure {
  if (status === 401) return { state: 'signed_out' };
  if (status === 404 && notFoundIsError) return { state: 'error', status, detail };
  if (OFFLINE.has(status)) return { state: 'offline', status };
  return { state: 'error', status, detail };
}

/** Extract a short human message from a FastAPI-style error body. */
export function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail.slice(0, 300);
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === 'string') return first.msg.slice(0, 300);
    }
  }
  return fallback;
}

export function dataOr<T>(result: ApiResult<T>, fallback: T): T {
  return result.state === 'ok' ? result.data : fallback;
}
