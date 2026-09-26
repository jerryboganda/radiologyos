import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyFailure } from './api-state.ts';
import { citationLink } from './citations.ts';
import { basisText, parseApproveForm, parseExtractForm, parseResolveForm } from './knowledge.ts';
import { optionLetter, parseExamForm, parseGenerateForm, questionFilters } from './questions.ts';
import { blockView, needsOnboarding, parseProfileForm } from './study.ts';
import type { ProfileOut } from './types/study.ts';

const ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [k, v] of entries) data.append(k, v);
  return data;
}

test('onboarding is shown for a missing profile or a 409 plan', () => {
  const ok = { state: 'ok' as const, data: {} };
  assert.equal(needsOnboarding(classifyFailure(404, 'set your exam date first'), ok), true);
  assert.equal(needsOnboarding(ok, classifyFailure(409, 'set your exam date first')), true);
  assert.equal(needsOnboarding(ok, ok), false);
  assert.equal(needsOnboarding(ok, { state: 'offline', status: 0 }), false);
});

test('profile form builds a full PUT body and keeps unedited fields', () => {
  const existing = { timezone: 'Asia/Karachi', weekday_minutes: 60, weekend_minutes: 180, reminder: { enabled: true, time: '07:00' } };
  const parsed = parseProfileForm(
    form([['exam_date', '2027-03-01'], ['daily_minutes', '90'], ['exam_targets', 'frcr'], ['exam_targets', 'bogus']]),
    existing as ProfileOut
  );
  assert.deepEqual(parsed, {
    ok: true,
    profile: {
      exam_date: '2027-03-01', exam_targets: ['frcr'], daily_minutes: 90, timezone: 'Asia/Karachi',
      weekday_minutes: 60, weekend_minutes: 180, reminder: { enabled: true, time: '07:00' }
    }
  });
  assert.equal(parseProfileForm(form([['exam_date', 'soon']])).ok, false);
  assert.equal(parseProfileForm(form([['exam_date', '2027-03-01'], ['daily_minutes', '5'], ['exam_targets', 'imm']])).ok, false);
  assert.equal(parseProfileForm(form([['exam_date', '2027-03-01'], ['daily_minutes', '90']])).ok, false);
});

test('plan blocks get copy and destinations', () => {
  assert.deepEqual(blockView({ kind: 'review', minutes: 30, due_cards: 12 }), { title: 'Review due cards', href: '#review', details: ['12 due cards'] });
  const learn = blockView({ kind: 'learn', minutes: 40, new_cards: 1, topics: [{ code: 'CH', title: 'Chest', minutes: 40, slots: 2 }] });
  assert.equal(learn.title, 'Learn: Chest');
  assert.deepEqual(learn.details, ['1 new card']);
  assert.equal(blockView({ kind: 'test', minutes: 20, mock_paper_suggested: true }).href, '/exams');
  assert.equal(blockView({ kind: 'viva', minutes: 10 }).href, '/questions?type=viva');
});

test('question generation, filters, and exam forms', () => {
  const ok = parseGenerateForm(form([['type', 'seq'], ['exam_target', 'imm'], ['count', '5'], ['source_ids', ID], ['source_ids', 'x']]));
  assert.deepEqual(ok, { ok: true, value: { type: 'seq', exam_target: 'imm', count: 5, topic: null, source_ids: [ID] } });
  assert.equal(parseGenerateForm(form([['type', 'rapid_recall'], ['exam_target', 'imm'], ['topic', 'chest']])).ok, false);
  assert.equal(parseGenerateForm(form([['type', 'sba'], ['exam_target', 'imm'], ['count', '6'], ['topic', 'chest']])).ok, false);
  assert.equal(parseGenerateForm(form([['type', 'sba'], ['exam_target', 'imm']])).ok, false, 'topic or sources required');
  assert.deepEqual(questionFilters(new URLSearchParams('type=viva&exam_target=nope&topic=a')), { type: 'viva', exam_target: null, topic: null });
  assert.equal(parseExamForm(form([['mode', 'exam'], ['count', '10']])).ok, false, 'timed exam needs a limit');
  assert.deepEqual(parseExamForm(form([['mode', 'practice'], ['count', '10']])), {
    ok: true,
    value: { mode: 'practice', count: 10, time_limit_minutes: null, exam_target: null, topic: null, types: ['sba'] }
  });
  assert.equal(optionLetter(2), 'C');
  assert.equal(optionLetter(null), '—');
});

test('knowledge forms and weight basis', () => {
  assert.deepEqual(parseResolveForm(form([['conflict_id', ID], ['resolution', ' Use the newer guideline '], ['preferred_claim_id', '']])), {
    ok: true,
    value: { conflictId: ID, body: { resolution: 'Use the newer guideline', preferred_claim_id: null } }
  });
  assert.equal(parseResolveForm(form([['conflict_id', ID], ['resolution', '  ']])).ok, false);
  assert.deepEqual(parseApproveForm(form([['exam_target', 'frcr']])), { ok: true, value: { exam_target: 'frcr', weight_ids: null } });
  assert.deepEqual(parseApproveForm(form([['exam_target', 'all'], ['weight_id', ID]])), { ok: true, value: { exam_target: 'all', weight_ids: [ID] } });
  assert.equal(parseExtractForm(form([['source_id', ID], ['mode', 'past_paper']])).ok, false, 'past paper needs an exam');
  assert.deepEqual(parseExtractForm(form([['source_id', ID], ['mode', 'past_paper'], ['exam_target', 'imm'], ['year', '2024']])), {
    ok: true,
    value: { sourceId: ID, body: { mode: 'past_paper', exam_target: 'imm', year: 2024 } }
  });
  assert.equal(basisText({ count: 12, total: 240, papers: 5, total_papers: 8, years: [2024, 2019] }), '12 of 240 questions · 5 of 8 papers · 2019–2024');
  assert.equal(basisText(null), '');
});

test('citationLink normalises every API citation envelope', () => {
  const tutor = { kind: 'source', source_id: ID, source_title: 'Grainger', page_from: 4, page_to: 5, block_refs: [{ page: 5, block: 2 }] };
  assert.deepEqual(citationLink(tutor), { kind: 'source', href: `/library/${ID}?page=5&block=2`, label: 'Grainger · p.4–5' });
  const knowledge = { source_id: ID, source_title: 'Notes', page_from: 7, page_to: 7, blocks: [{ page_no: 7, block_no: 3, bbox: [0, 0, 1, 1] }] };
  assert.equal(citationLink(knowledge)?.href, `/library/${ID}?page=7&block=3`);
  const figure = { kind: 'figure', figure_id: ID, source_id: ID, source_title: 'Atlas', page_no: 9 };
  assert.deepEqual(citationLink(figure), { kind: 'source', href: `/library/${ID}?page=9`, label: 'Atlas · p.9 · figure' });
  assert.deepEqual(citationLink({ kind: 'web', url: 'https://www.radiopaedia.org/a' }), {
    kind: 'web',
    href: 'https://www.radiopaedia.org/a',
    label: 'From the web · radiopaedia.org'
  });
  assert.equal(citationLink({ kind: 'web', url: 'javascript:alert(1)' }), null);
  assert.equal(citationLink({ source_id: '../etc' }), null);
  assert.equal(citationLink(null), null);
});
