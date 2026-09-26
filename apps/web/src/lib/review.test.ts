import assert from 'node:assert/strict';
import { test } from 'node:test';
import { answeredCount, isWritten, pendingChanges, rebase } from './exam-session.ts';
import { parseExamForm } from './questions.ts';
import { parseReviewForm, reviewMessage } from './review.ts';

const ORIGINAL = {
  stem: 'Most likely diagnosis?',
  topic: 'PAP',
  explanation: 'x',
  options: ['A', 'B', 'C', 'D', 'E'],
  key: 0,
  model_answer: ''
};

function form(entries: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(entries)) {
    for (const v of Array.isArray(value) ? value : [value]) data.append(name, v);
  }
  return data;
}

test('approve and reject carry no fields; unknown actions are refused', () => {
  assert.deepEqual(parseReviewForm(form({ action: 'approve', stem: 'ignored' }), ORIGINAL), { ok: true, value: { action: 'approve' } });
  assert.deepEqual(parseReviewForm(form({ action: 'reject' }), ORIGINAL), { ok: true, value: { action: 'reject' } });
  assert.equal(parseReviewForm(form({ action: 'delete' }), ORIGINAL).ok, false);
});

test('edit sends only changed fields and validates the options and key', () => {
  const options = { option_0: 'A', option_1: 'B', option_2: 'C', option_3: 'D', option_4: 'E' };
  const changed = parseReviewForm(form({ action: 'edit', stem: 'Which diagnosis?', topic: 'PAP', ...options, key_index: '2' }), ORIGINAL);
  assert.deepEqual(changed, { ok: true, value: { action: 'edit', stem: 'Which diagnosis?', key_index: 2 } });
  const same = parseReviewForm(form({ action: 'edit', stem: ORIGINAL.stem, ...options, key_index: '0' }), ORIGINAL);
  assert.deepEqual(same, { ok: false, error: 'Nothing was changed.' });
  assert.equal(parseReviewForm(form({ action: 'edit', ...options, option_3: ' ', key_index: '0' }), ORIGINAL).ok, false);
  assert.equal(parseReviewForm(form({ action: 'edit', stem: '   ' }), ORIGINAL).ok, false);
});

test('review refusals read as sentences', () => {
  assert.match(reviewMessage('citations_stale'), /no longer exists/);
  assert.match(reviewMessage('sba_options_not_distinct,sba_stem_too_long'), /distinct.*120 words/);
  assert.equal(reviewMessage('something_new'), 'something_new');
});

test('exam form chooses item types and defaults to SBA', () => {
  const base = { mode: 'practice', count: '10' };
  const mixed = parseExamForm(form({ ...base, types: ['sba', 'seq', 'bogus'] }));
  assert.ok(mixed.ok && mixed.value.types?.join() === 'sba,seq');
  const plain = parseExamForm(form(base));
  assert.ok(plain.ok && plain.value.types?.join() === 'sba');
  assert.equal(parseExamForm(form({ ...base, types: ['bogus'] })).ok, false);
});

test('written answers count as answered and diff like options', () => {
  const ids = ['a', 'b', 'c'];
  assert.equal(answeredCount(ids, { a: 1 }, { b: 'crazy paving', c: '   ' }), 2);
  assert.ok(isWritten('seq') && isWritten('viva') && !isWritten('sba'));
  assert.deepEqual(pendingChanges<string>({ b: 'old', c: 'gone' }, { b: 'new' }), { b: 'new', c: null });
  assert.deepEqual(rebase<string>({ b: 'server', d: 'other tab' }, { b: 'old' }, { b: 'mine' }), { b: 'mine', d: 'other tab' });
});
