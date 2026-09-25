import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    preview_reads: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

const baseUrl = __ENV.RADBRAIN_PREVIEW_URL || 'http://127.0.0.1:3000';
const headers = {
  'x-user-id': '10000000-0000-0000-0000-000000000001',
  'x-tenant-id': '20000000-0000-0000-0000-000000000002',
  'x-role': 'student',
};

export default function () {
  const health = http.get(`${baseUrl}/api/health`);
  check(health, { 'web health is 200': (response) => response.status === 200 });
  const page = http.get(`${baseUrl}/preview`, { headers });
  check(page, { 'preview page is 200': (response) => response.status === 200 });
  sleep(1);
}
