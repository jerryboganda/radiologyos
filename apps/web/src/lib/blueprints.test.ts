import assert from 'node:assert/strict';
import { test } from 'node:test';
import { itemsText, markingText, mixText, parseBlueprintOverrideForm } from './blueprints.ts';
import { isCurriculumFilter, parseCurriculumDecisionForm } from './knowledge.ts';
import { parseExamForm } from './questions.ts';

const HASH = 'a'.repeat(64);

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [k, v] of entries) data.append(k, v);
  return data;
}

test('blueprint summaries say what is and is not published', () => {
  assert.equal(itemsText({ items: { sba: 120, seq: 0 }, duration_minutes: 180 }), '120 SBA · 180 min');
  assert.equal(
    markingText({ negative_marking: { enabled: false, penalty: 0 }, pass_mark_percent: null }),
    'No negative marking · pass mark not published'
  );
  assert.equal(
    markingText({ negative_marking: { enabled: true, penalty: 0.25 }, pass_mark_percent: 70 }),
    'Negative marking −0.25 per wrong SBA · pass mark 70%'
  );
  assert.equal(mixText({ mix_mode: 'fixed', mix: [{ label: 'Chest', systems: ['CHEST'], share: 0.55 }] }), 'Chest 55%');
  assert.match(mixText({ mix_mode: 'weights', mix: [] }), /past-paper weights/);
});

test('blueprint override form keeps blanks as defaults and bounds values', () => {
  assert.deepEqual(parseBlueprintOverrideForm(form([['blueprint_id', 'imm_theory']])), {
    ok: true,
    value: { id: 'imm_theory', overrides: {} }
  });
  assert.deepEqual(
    parseBlueprintOverrideForm(form([['blueprint_id', 'imm_theory'], ['duration_minutes', '90'], ['penalty', '0.25']])),
    {
      ok: true,
      value: { id: 'imm_theory', overrides: { duration_minutes: 90, negative_marking: { enabled: true, penalty: 0.25 } } }
    }
  );
  assert.equal(parseBlueprintOverrideForm(form([['blueprint_id', 'x'], ['penalty', '2']])).ok, false);
  assert.equal(parseBlueprintOverrideForm(form([['blueprint_id', 'x'], ['duration_minutes', '1.5']])).ok, false);
  assert.equal(parseBlueprintOverrideForm(form([['blueprint_id', 'Bad Id']])).ok, false);
});

test('exam form builds blueprint papers without a time limit', () => {
  assert.deepEqual(parseExamForm(form([['mode', 'exam'], ['count', '20'], ['blueprint_id', 'frcr_2a'], ['blueprint_items', '30']])), {
    ok: true,
    value: { mode: 'exam', count: 30, time_limit_minutes: null, topic: null, blueprint_id: 'frcr_2a', blueprint_items: 30 }
  });
  assert.equal(parseExamForm(form([['mode', 'exam'], ['blueprint_id', 'frcr_2a'], ['blueprint_items', '0']])).ok, false);
  assert.equal(parseExamForm(form([['mode', 'exam'], ['blueprint_id', 'BAD']])).ok, false);
});

test('curriculum decisions are hash-bound and rejections need a reason', () => {
  assert.deepEqual(parseCurriculumDecisionForm(form([['decision', 'approved'], ['content_hash', HASH]])), {
    ok: true,
    value: { decision: 'approved', content_hash: HASH, notes: '' }
  });
  assert.equal(parseCurriculumDecisionForm(form([['decision', 'rejected'], ['content_hash', HASH]])).ok, false);
  assert.equal(parseCurriculumDecisionForm(form([['decision', 'approved'], ['content_hash', 'x']])).ok, false);
  assert.equal(isCurriculumFilter('frcr_2b'), true);
  assert.equal(isCurriculumFilter('all'), false);
});
