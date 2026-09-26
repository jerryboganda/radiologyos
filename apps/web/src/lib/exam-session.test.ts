import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  answeredCount,
  clockOffset,
  formatClock,
  parseRecentExams,
  pendingChanges,
  rebase,
  remainingMs,
  retryDelay,
  saveOutcome,
  withRecentExam
} from './exam-session.ts';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

test('the timer follows the server clock, not the device clock', () => {
  // Device clock is 60 s behind the server.
  const clientNow = Date.parse('2026-09-26T10:00:00Z');
  const offset = clockOffset('2026-09-26T10:01:00Z', clientNow);
  assert.equal(offset, 60_000);
  const deadline = '2026-09-26T10:31:00Z';
  assert.equal(remainingMs(deadline, offset, clientNow), 30 * 60_000);
  assert.equal(remainingMs(deadline, offset, clientNow + 31 * 60_000), 0);
  assert.equal(remainingMs(null, offset, clientNow), null);
  assert.equal(clockOffset('garbage', clientNow), 0);
});

test('formatClock rounds up and shows hours only when needed', () => {
  assert.equal(formatClock(65_000), '01:05');
  assert.equal(formatClock(3_725_000), '1:02:05');
  assert.equal(formatClock(400), '00:01');
  assert.equal(formatClock(0), '00:00');
  assert.equal(formatClock(-5), '00:00');
});

test('pendingChanges sends changed options and null for cleared answers', () => {
  assert.deepEqual(pendingChanges({ [A]: 1, [B]: 2 }, { [A]: 3, [B]: 2 }), { [A]: 3 });
  assert.deepEqual(pendingChanges({ [A]: 1 }, {}), { [A]: null });
  assert.deepEqual(pendingChanges({}, {}), {});
});

test('rebase adopts the server copy and replays unsaved local edits', () => {
  const saved = { [A]: 0 };
  const local = { [A]: 2 }; // this tab changed A but the save hit 409
  const server = { [A]: 0, [B]: 4 }; // another tab answered B
  assert.deepEqual(rebase(server, saved, local), { [A]: 2, [B]: 4 });
  // A local clear survives the rebase too.
  assert.deepEqual(rebase({ [A]: 1, [B]: 4 }, { [A]: 1 }, {}), { [B]: 4 });
});

test('saveOutcome maps autosave responses', () => {
  assert.equal(saveOutcome(200, null), 'saved');
  assert.equal(saveOutcome(409, 'stale_revision'), 'stale');
  assert.equal(saveOutcome(409, 'exam_time_expired'), 'closed');
  assert.equal(saveOutcome(409, 'exam_submitted'), 'closed');
  assert.equal(saveOutcome(404, 'exam not found'), 'stale');
  assert.equal(saveOutcome(0, null), 'retry');
  assert.equal(saveOutcome(503, 'network'), 'retry');
  assert.equal(saveOutcome(422, 'invalid_answer'), 'error');
  assert.equal(retryDelay(0), 1000);
  assert.equal(retryDelay(10), 30_000);
});

test('answered count and the recent-exams cookie', () => {
  assert.equal(answeredCount([A, B], { [A]: 0 }), 1);
  assert.deepEqual(parseRecentExams(`${A},../x,${B},${A}`), [A, B]);
  assert.deepEqual(parseRecentExams(undefined), []);
  assert.deepEqual(withRecentExam([A, B], B), [B, A]);
  assert.deepEqual(withRecentExam([A], 'nope'), [A]);
});
