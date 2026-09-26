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
import { Counter } from 'k6/metrics';

const authRefusals = new Counter('radbrain_auth_refusals');
const serverErrors = new Counter('radbrain_server_errors');

// A refusal is a correct outcome, not a transport failure, so 401/403/404 must
// not be counted as failed requests. Anything 5xx still is.
http.setResponseCallback(http.expectedStatuses(200, 401, 403, 404));

export const options = {
  scenarios: {
    health_reads: {
      executor: 'constant-vus',
      vus: Number(__ENV.RADBRAIN_LOAD_VUS || 5),
      duration: __ENV.RADBRAIN_LOAD_DURATION || '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate>0.99'],
  },
};

const baseUrl = __ENV.RADBRAIN_API_URL || 'http://api:8000';

export default function () {
  const health = http.get(`${baseUrl}/health/live`);
  check(health, { 'api liveness is 200': (r) => r.status === 200 });

  const ready = http.get(`${baseUrl}/health/ready`);
  check(ready, { 'api readiness is 200': (r) => r.status === 200 });

  // A genuinely protected route must refuse an anonymous caller; a 404 on an
  // absent route would prove nothing about auth.
  const denied = http.get(`${baseUrl}/v1/admin/ping`);
  const deniedOk = check(denied, {
    'anonymous admin probe is refused': (r) => r.status === 401 || r.status === 403,
  });
  if (deniedOk) authRefusals.add(1);

  // The in-memory preview surface was removed (ADR 0031): its paths are absent.
  const retired = http.get(`${baseUrl}/v1/preview/sources`);
  check(retired, { 'retired preview surface is absent': (r) => r.status === 404 });

  if (health.status >= 500 || ready.status >= 500 || denied.status >= 500) {
    serverErrors.add(1);
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
      `auth refusals: ${m.radbrain_auth_refusals ? m.radbrain_auth_refusals.values.count : 0}\n` +
      `5xx responses: ${m.radbrain_server_errors ? m.radbrain_server_errors.values.count : 0}\n` +
      `checks: ${v('checks')}\n`,
  };
}
