import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyFailure, failureText, isKind, isRetryable, loadProblem, MESSAGES } from './api-state.ts';

test('model and usage failures map to friendly states', () => {
  const unavailable = classifyFailure(503, 'model runtime is not available');
  assert.equal(unavailable.state === 'error' && unavailable.kind, 'unavailable');
  assert.equal(failureText(unavailable), MESSAGES.unavailable);

  // The assessment API reports its usage limit as 503; the tutor uses 429.
  for (const failure of [classifyFailure(503, 'model usage limit reached; retry later'), classifyFailure(429, 'x')]) {
    assert.equal(failure.state === 'error' && failure.kind, 'usage_limit');
    assert.equal(failureText(failure), MESSAGES.usage_limit);
    assert.equal(isRetryable(failure), true);
  }

  const failed = classifyFailure(502, 'model call failed');
  assert.equal(failed.state === 'error' && failed.kind, 'model_failed');
  assert.equal(failureText(failed), MESSAGES.model_failed);
  assert.equal(isRetryable(failed), true);
});

test('coming-online is reserved for network failures', () => {
  assert.equal(classifyFailure(0, '').state, 'offline');
  assert.equal(classifyFailure(504, 'Request failed (504)', false).state, 'offline');
  assert.equal(classifyFailure(503, 'push is not configured', true).state, 'error');
  assert.deepEqual(loadProblem({ state: 'offline', status: 0 }), { offline: true, message: MESSAGES.offline });
  assert.equal(loadProblem({ state: 'ok', data: 1 }), null);
});

test('409 onboarding/conflicts and 404s keep their API detail', () => {
  const onboarding = classifyFailure(409, 'set your exam date first');
  assert.equal(isKind(onboarding, 'conflict'), true);
  assert.equal(failureText(onboarding), 'set your exam date first');
  assert.equal(isKind(classifyFailure(404, 'thread not found'), 'not_found'), true);
  assert.equal(isKind(classifyFailure(403, 'forbidden'), 'forbidden'), true);
  assert.equal(isRetryable(classifyFailure(422, 'bad')), false);
  assert.equal(failureText({ state: 'signed_out' }), MESSAGES.signed_out);
});
