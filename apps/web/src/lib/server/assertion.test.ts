import assert from 'node:assert/strict';
import test from 'node:test';
import { jwtVerify } from 'jose';
import { ASSERTION_AUDIENCE, ASSERTION_ISSUER, ApiUnavailable, signAssertion } from './assertion.ts';

const secret = 'x'.repeat(40);

test('signs a short-lived assertion that carries only the subject', async () => {
  const token = await signAssertion('user-123', secret);
  const { payload, protectedHeader } = await jwtVerify(token, new TextEncoder().encode(secret), {
    issuer: ASSERTION_ISSUER,
    audience: ASSERTION_AUDIENCE
  });
  assert.equal(protectedHeader.alg, 'HS256');
  assert.equal(payload.sub, 'user-123');
  assert.ok((payload.exp ?? 0) - (payload.iat ?? 0) <= 120);
  assert.deepEqual(Object.keys(payload).sort(), ['aud', 'exp', 'iat', 'iss', 'sub']);
});

test('refuses to sign without a strong secret or a subject', async () => {
  await assert.rejects(signAssertion('user', 'short'), ApiUnavailable);
  await assert.rejects(signAssertion('user', undefined), ApiUnavailable);
  await assert.rejects(signAssertion('  ', secret), ApiUnavailable);
});
