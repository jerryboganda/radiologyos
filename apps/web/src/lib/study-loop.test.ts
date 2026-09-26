import assert from 'node:assert/strict';
import { test } from 'node:test';
import { calibrationCopy, cellLabel, cellStyle, coverageLevel, projectionCopy } from './heatmap.ts';
import { nextUnanswered, parseAnswerForm, parseStepRef, progressPercent, selectedStep, summaryLine } from './session.ts';
import { ignoreKey, isTypingTarget, optionKey, reviewKey, sbaKey } from './shortcuts.ts';
import type { Calibration, Projection, SessionStep } from './types/session.ts';

const SID = '6f1c0f7e-3c4b-4d7e-9a53-1c2b3d4e5f60';
const QID = '0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(entries)) data.append(name, value);
  return data;
}

test('typing targets and modifiers switch shortcuts off', () => {
  assert.equal(isTypingTarget({ tagName: 'TEXTAREA' }), true);
  assert.equal(isTypingTarget({ tagName: 'input', type: 'text' }), true);
  assert.equal(isTypingTarget({ tagName: 'INPUT' }), true);
  assert.equal(isTypingTarget({ tagName: 'INPUT', type: 'radio' }), false);
  assert.equal(isTypingTarget({ tagName: 'DIV', isContentEditable: true }), true);
  assert.equal(isTypingTarget({ tagName: 'BUTTON' }), false);
  assert.equal(isTypingTarget(null), false);
  assert.equal(ignoreKey({ key: '1', ctrlKey: true }), true);
  assert.equal(ignoreKey({ key: 'a', isComposing: true }), true);
  assert.equal(reviewKey({ key: '3', target: { tagName: 'TEXTAREA' } }, true), null);
  // Space/Enter on a focused button or link stay native; digits still work there.
  assert.equal(reviewKey({ key: ' ', target: { tagName: 'BUTTON' } }, false), null);
  assert.equal(sbaKey({ key: 'Enter', target: { tagName: 'A' } }, 5), null);
  assert.deepEqual(reviewKey({ key: '2', target: { tagName: 'BUTTON' } }, true), { kind: 'rate', rating: 2 });
});

test('card review: space reveals, then 1–4 rate', () => {
  assert.deepEqual(reviewKey({ key: ' ' }, false), { kind: 'reveal' });
  assert.deepEqual(reviewKey({ key: 'Enter' }, false), { kind: 'reveal' });
  assert.equal(reviewKey({ key: '3' }, false), null);
  assert.deepEqual(reviewKey({ key: '1' }, true), { kind: 'rate', rating: 1 });
  assert.deepEqual(reviewKey({ key: '4' }, true), { kind: 'rate', rating: 4 });
  assert.equal(reviewKey({ key: '5' }, true), null);
  assert.equal(reviewKey({ key: ' ' }, true), null);
  assert.equal(reviewKey({ key: '1', metaKey: true }, true), null);
});

test('SBA: A–E choose, 1–3 confidence, Enter submits', () => {
  assert.equal(optionKey({ key: 'a' }, 5), 0);
  assert.equal(optionKey({ key: 'E' }, 5), 4);
  assert.equal(optionKey({ key: 'e' }, 4), null);
  assert.equal(optionKey({ key: 'F' }, 5), null);
  assert.equal(optionKey({ key: 'Escape' }, 5), null);
  assert.deepEqual(sbaKey({ key: 'c' }, 5), { kind: 'choose', option: 2 });
  assert.deepEqual(sbaKey({ key: '2' }, 5), { kind: 'confidence', level: 2 });
  assert.equal(sbaKey({ key: '4' }, 5), null);
  assert.deepEqual(sbaKey({ key: 'Enter' }, 5), { kind: 'submit' });
  assert.equal(sbaKey({ key: 'b', target: { tagName: 'INPUT', type: 'search' } }, 5), null);
  assert.deepEqual(sbaKey({ key: 'b', target: { tagName: 'INPUT', type: 'radio' } }, 5), { kind: 'choose', option: 1 });
});

function step(no: number, status: SessionStep['status']): SessionStep {
  return { step_no: no, kind: 'learn', status, minutes: 5, started_at: null, deadline_at: null, completed_at: null, review: null, learn: null, test: null, viva: null };
}

test('session progress, resume and SBA navigation', () => {
  const session = { steps: [step(1, 'done'), step(2, 'active'), step(3, 'pending')], current_step: 2, progress: { done: 1, total: 3 } };
  assert.equal(progressPercent(session), 33);
  assert.equal(selectedStep(session)?.step_no, 2);
  assert.equal(selectedStep(session, 3)?.step_no, 3);
  assert.equal(selectedStep({ ...session, current_step: null })?.step_no, 3);
  assert.equal(progressPercent({ progress: { done: 0, total: 0 } }), 0);
  const q = (id: string) => ({ id }) as never;
  const block = { questions: [q('a'), q('b'), q('c')], results: [{ question_id: 'b' } as never] };
  assert.equal(nextUnanswered(block), 'a');
  assert.equal(nextUnanswered(block, 'a'), 'c');
  assert.equal(nextUnanswered(block, 'c'), 'a');
  assert.equal(nextUnanswered({ ...block, results: ['a', 'b', 'c'].map((id) => ({ question_id: id }) as never) }), null);
});

test('answer and step forms are validated before they reach the API', () => {
  assert.deepEqual(parseStepRef(form({ session_id: SID, step_no: '2' })), { ok: true, value: { sessionId: SID, stepNo: 2 } });
  assert.equal(parseStepRef(form({ session_id: 'x', step_no: '2' })).ok, false);
  assert.equal(parseStepRef(form({ session_id: SID, step_no: '0' })).ok, false);
  assert.deepEqual(parseAnswerForm(form({ question_id: QID, selected_option: '2', confidence: '3' })), {
    ok: true,
    value: { question_id: QID, selected_option: 2, confidence: 3 }
  });
  assert.deepEqual(parseAnswerForm(form({ question_id: QID, selected_option: '0' })), {
    ok: true,
    value: { question_id: QID, selected_option: 0, confidence: null }
  });
  assert.equal(parseAnswerForm(form({ question_id: QID })).ok, false);
  assert.equal(parseAnswerForm(form({ question_id: QID, selected_option: '5' })).ok, false);
  assert.equal(parseAnswerForm(form({ question_id: QID, selected_option: '1', confidence: '4' })).ok, false);
  assert.deepEqual(parseAnswerForm(form({ answer_text: '  Crazy paving.  ' })), { ok: true, value: { answer_text: 'Crazy paving.' } });
  assert.equal(parseAnswerForm(form({ answer_text: '   ' })).ok, false);
  const line = summaryLine({ steps_done: 3, steps_total: 4, steps_skipped: 1, reviews: 12, sba_answered: 10, sba_correct: 7, viva_answered: true, minutes: 58, weighted_coverage: 0.3 });
  assert.equal(line, '3 of 4 steps done · 12 cards reviewed · 7/10 SBA correct · viva answered · about 58 min.');
});

test('heatmap scale is stepped, theme-token based and labelled', () => {
  assert.equal(coverageLevel(null), null);
  assert.equal(coverageLevel(0), 0);
  assert.equal(coverageLevel(0.49), 2);
  assert.equal(coverageLevel(1.4), 4);
  assert.equal(cellStyle(null), 'background-color: var(--surface-2)');
  assert.match(cellStyle(1), /color-mix\(in oklab, var\(--ok\) 46%, var\(--surface\)\)/);
  assert.notEqual(cellStyle(0.1), cellStyle(0.9));
  const cell = { code: 'CHEST.ILD', title: 'ILD', material: 8, studied: 4, coverage: 0.5, accuracy: 0.75, band: 'learning' as const };
  assert.equal(cellLabel('Chest', cell), 'Chest · ILD: 50% covered (4/8 passages), accuracy 75%');
  assert.equal(cellLabel('Chest', { ...cell, coverage: null }), 'Chest · ILD: no mapped passages yet');
});

const PROJECTION: Projection = {
  status: 'behind', days_remaining: 119, target_days: 89, goal: 0.9, coverage: 0.3, remaining_weighted: 0.7,
  topics_remaining: 12, sessions_in_window: 3, coverage_per_day: 0.001, minutes_per_day: 40,
  projected_coverage: 0.42, needed_minutes_per_day: 95, needed_hours_per_day: 1.6
};

test('projection and calibration copy never mention a pass probability', () => {
  const behind = projectionCopy(PROJECTION);
  assert.equal(behind.tone, 'warn');
  assert.match(behind.headline, /42% coverage projected/);
  assert.match(behind.detail, /About 1\.6 h a day reaches 90% coverage in 89 days/);
  assert.equal(projectionCopy({ ...PROJECTION, status: 'insufficient_history' }).tone, 'info');
  assert.equal(projectionCopy({ ...PROJECTION, status: 'done' }).headline, 'Coverage goal reached');
  const cal: Calibration = {
    rated: 20, bias: 0.24, verdict: 'overconfident', levels: [], wrong: 9, confident_wrong: 6, confident_wrong_share: 0.67, min_rated: 10
  };
  const copy = calibrationCopy(cal);
  assert.equal(copy.headline, 'Overconfident (bias +24 points)');
  assert.match(copy.detail, /6 wrong answers were rated high confidence/);
  assert.match(calibrationCopy({ ...cal, verdict: 'insufficient', rated: 3 }).detail, /after 10 rated answers \(3 so far\)/);
  for (const text of [behind.headline, behind.detail, copy.headline, copy.detail]) assert.doesNotMatch(text, /probab|pass/i);
});
