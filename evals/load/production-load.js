// Load check for the deployed production stack on the shared platform VPS.
//
// Deliberately small: the owner asked that this host not be strained, so this
// is a ceiling check rather than a saturation test. Five VUs for 30s against
// read-only endpoints puts the api container at a few percent CPU, which the
// resource caps absorb. Raising vus here is a decision, not a tweak.
//
// Run with the api reached from inside the platform network, because no port
// is published on 0.0.0.0.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const searchLatency = new Trend('radbrain_search_duration', true);
const tutorLatency = new Trend('radbrain_tutor_duration', true);
const refusals = new Counter('radbrain_grounding_refusals');
const authRefusals = new Counter('radbrain_auth_refusals');
const serverErrors = new Counter('radbrain_server_errors');

// A refusal is a correct outcome, not a transport failure, so 401/403/404 must
// not be counted as failed requests. Anything 5xx still is.
http.setResponseCallback(http.expectedStatuses(200, 401, 403, 404));

export const options = {
  scenarios: {
    preview_reads: {
      executor: 'constant-vus',
      vus: Number(__ENV.RADBRAIN_LOAD_VUS || 5),
      duration: __ENV.RADBRAIN_LOAD_DURATION || '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate>0.99'],
    // A grounded tutor answer must stay interactive; a refusal is cheap.
    radbrain_tutor_duration: ['p(95)<1000'],
  },
};

const baseUrl = __ENV.RADBRAIN_API_URL || 'http://api:8000';
const tenant = __ENV.RADBRAIN_LOAD_TENANT || '30000000-0000-0000-0000-00000000000a';
const user = __ENV.RADBRAIN_LOAD_USER || '10000000-0000-0000-0000-00000000000a';

// Authenticated preview checks are opt-in and only run against a local or test
// stack; production only proves the surface refuses anonymous callers.
const previewEnabled = (__ENV.RADBRAIN_LOAD_PREVIEW || '0') === '1';

const headers = {
  'x-user-id': user,
  'x-tenant-id': tenant,
  'x-role': 'student',
  'content-type': 'application/json',
};

export default function () {
  const health = http.get(`${baseUrl}/health/live`);
  check(health, { 'api liveness is 200': (r) => r.status === 200 });

  const ready = http.get(`${baseUrl}/health/ready`);
  check(ready, { 'api readiness is 200': (r) => r.status === 200 });

  // A genuinely protected route must refuse an anonymous caller. Probed on the
  // data-rights route because it exists in every environment; the preview
  // surface is absent in production, so a 404 there proves nothing about auth.
  const denied = http.get(`${baseUrl}/v1/admin/ping`);
  const deniedOk = check(denied, {
    'anonymous admin probe is refused': (r) => r.status === 401 || r.status === 403,
  });
  if (deniedOk) authRefusals.add(1);

  // Preview is enabled in production behind OIDC (ADR 0009), so an anonymous
  // caller must be refused; 404 (surface off) is also acceptable.
  const preview = http.get(`${baseUrl}/v1/preview/sources`);
  if (!previewEnabled) {
    check(preview, {
      'preview is gated in production': (r) => [401, 403, 404].includes(r.status),
    });
  }

  if (health.status >= 500 || ready.status >= 500 || denied.status >= 500) {
    serverErrors.add(1);
  }

  if (!previewEnabled) {
    sleep(1);
    return;
  }

  const search = http.post(
    `${baseUrl}/v1/preview/search`,
    JSON.stringify({ query: 'costophrenic angle', limit: 5 }),
    { headers },
  );
  searchLatency.add(search.timings.duration);
  check(search, { 'search is 200': (r) => r.status === 200 });

  const tutor = http.post(
    `${baseUrl}/v1/preview/tutor/ask`,
    JSON.stringify({ query: 'costophrenic angle' }),
    { headers },
  );
  tutorLatency.add(tutor.timings.duration);
  const answered = check(tutor, { 'tutor is 200': (r) => r.status === 200 });
  if (answered && tutor.status === 200) {
    const body = tutor.json();
    // A refusal is a correct outcome, not a failure, but count it so the
    // grounding rate is visible rather than assumed.
    if (body && typeof body.answer === 'string' && body.answer.startsWith('I do not have')) {
      refusals.add(1);
    }
    check(tutor, {
      'tutor answer is cited or explicitly refused': (r) => {
        const parsed = r.json();
        if (!parsed) return false;
        if (parsed.answer && parsed.answer.startsWith('I do not have')) {
          return Array.isArray(parsed.citations) && parsed.citations.length === 0;
        }
        return Array.isArray(parsed.citations) && parsed.citations.length > 0;
      },
    });
  }

  sleep(1);
}

export function handleSummary(data) {
  const m = data.metrics;
  const v = (k) => (m[k] ? JSON.stringify(m[k].values) : 'n/a');
  return {
    stdout:
      `\n--- radbrain load summary ---\n` +
      `http_req_failed: ${v('http_req_failed')}\n` +
      `http_req_duration: ${v('http_req_duration')}\n` +
      `search p95: ${v('radbrain_search_duration')}\n` +
      `tutor  p95: ${v('radbrain_tutor_duration')}\n` +
      `auth refusals: ${m.radbrain_auth_refusals ? m.radbrain_auth_refusals.values.count : 0}\n` +
      `grounding refusals: ${m.radbrain_grounding_refusals ? m.radbrain_grounding_refusals.values.count : 0}\n` +
      `5xx responses: ${m.radbrain_server_errors ? m.radbrain_server_errors.values.count : 0}\n` +
      `checks: ${v('checks')}\n`,
  };
}
