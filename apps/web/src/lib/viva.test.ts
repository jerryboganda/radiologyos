import assert from 'node:assert/strict';
import { test } from 'node:test';
import { composeStaged, isWaiting, parseStartForm, percentOf, splitStaged, vivaError } from './viva.ts';

const FIGURE = '11111111-1111-4111-8111-111111111111';

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

test('a topic viva parses with defaults and drops blank limits', () => {
  const parsed = parseStartForm(form({ topic: '  crazy paving ', max_turns: '', time_limit_minutes: '' }));
  assert.deepEqual(parsed, {
    ok: true,
    value: {
      kind: 'viva',
      style: 'practice',
      topic: 'crazy paving',
      figure_id: null,
      question_id: null,
      max_turns: null,
      time_limit_minutes: null
    }
  });
});

test('a staged case from a figure needs no topic and ignores max_turns', () => {
  const parsed = parseStartForm(form({ kind: 'image_case', style: 'fcps2_toacs', figure_id: FIGURE, max_turns: '9' }));
  assert.ok(parsed.ok);
  assert.equal(parsed.value.figure_id, FIGURE);
  assert.equal(parsed.value.max_turns, null);
});

test('bad input is refused before it reaches the API', () => {
  assert.equal(parseStartForm(form({ topic: 'x' })).ok, false);
  assert.equal(parseStartForm(form({ topic: 'PAP', kind: 'oral' })).ok, false);
  assert.equal(parseStartForm(form({ topic: 'PAP', style: 'mcq' })).ok, false);
  assert.equal(parseStartForm(form({ figure_id: 'not-a-uuid' })).ok, false);
  assert.equal(parseStartForm(form({ question_id: FIGURE })).ok, false);
  assert.equal(parseStartForm(form({ topic: 'PAP', max_turns: '40' })).ok, false);
  assert.equal(parseStartForm(form({ topic: 'PAP', time_limit_minutes: '0' })).ok, false);
});

test('staged answers round-trip through the exam text format', () => {
  const text = composeStaged({ describe: 'Axial CT', diagnosis: ' PAP ', findings: '   ' });
  assert.equal(text, '[describe]\nAxial CT\n[diagnosis]\nPAP');
  assert.deepEqual(splitStaged(`notes\n${text}`), { describe: 'Axial CT', diagnosis: 'PAP' });
  assert.deepEqual(splitStaged('free text only'), {});
});

test('the page polls only while the examiner works', () => {
  assert.equal(isWaiting({ status: 'preparing', work: 'pending' }), true);
  assert.equal(isWaiting({ status: 'active', work: 'running' }), true);
  assert.equal(isWaiting({ status: 'active', work: 'none' }), false);
  assert.equal(isWaiting({ status: 'finished', work: 'none' }), false);
});

test('codes map to readable messages and percentages are safe', () => {
  assert.match(vivaError('viva_examiner_busy'), /still marking/);
  assert.equal(vivaError('something_else'), 'something_else');
  assert.equal(percentOf(7, 8), 87.5);
  assert.equal(percentOf(1, 0), 0);
});
