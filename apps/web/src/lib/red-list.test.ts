import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  countsLabel,
  isRedList,
  isSummary,
  itemPage,
  kindLabel,
  pagesLabel,
  parseFactForm,
  parseStatus,
  parseVerdictForm,
  reasonHint,
  reasonText,
  redCount,
  sortByPage,
  summaryCount,
  topReasons
} from './red-list.ts';
import type { FileSummary, FlaggedFact, RedItem } from './types/red-list.ts';

const ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';
const SRC = '9b1c2d3e-4f5a-4b6c-8d7e-0f1a2b3c4d5e';

function item(overrides: Partial<RedItem> = {}): RedItem {
  return {
    id: ID,
    source_id: SRC,
    source_title: 'Chest imaging',
    file_name: 'chest.pdf',
    kind: 'page',
    page_from: 12,
    page_to: 12,
    reason: 'low_text_coverage',
    status: 'review',
    verdict: null,
    note: null,
    created_at: '2026-09-27T08:00:00Z',
    page_status: 'done',
    own_text: 'Synthetic page text',
    reading: 'Synthetic reading',
    figures: [],
    section_heading: null,
    section_text: null,
    statements: [],
    ...overrides
  };
}

function fact(overrides: Partial<FlaggedFact> = {}): FlaggedFact {
  return {
    id: ID,
    statement: 'Synthetic statement',
    doubt: 'Synthetic doubt',
    evidence_span: 'Synthetic evidence',
    source_id: SRC,
    source_title: 'Chest imaging',
    file_name: 'chest.pdf',
    page_from: 3,
    page_to: 4,
    status: 'flagged',
    note: null,
    decided_at: null,
    section_heading: 'Synthetic heading',
    section_text: 'Synthetic section with Synthetic evidence',
    ...overrides
  };
}

function summary(overrides: Partial<FileSummary> = {}): FileSummary {
  return {
    source_id: SRC,
    source_title: 'Chest imaging',
    file_name: 'chest.pdf',
    open_pages: 12,
    open_figures: 3,
    open_notes: 40,
    open_facts: 7,
    reviewed: 2,
    reasons: { low_text_coverage: 10, unsupported_claims: 40, empty_reading: 2 },
    ...overrides
  };
}

const FIGURE = {
  id: ID,
  figure_no: 1,
  caption: null,
  description: 'Synthetic reading',
  modality: 'CT',
  anatomy: null,
  findings: ['Synthetic finding'],
  source_quote: null,
  impression_origin: null,
  has_image: true
};

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [k, v] of entries) data.append(k, v);
  return data;
}

test('every known reason code has a plain-English sentence', () => {
  assert.equal(reasonText('low_text_coverage'), "The reading missed part of this page's own text");
  assert.equal(reasonText('empty_reading_of_text_page'), 'No text could be read from a page that has text');
  assert.equal(reasonText('bbox_out_of_range'), 'The page layout could not be mapped');
  assert.equal(reasonText('empty_reading'), 'Nothing could be read from this image');
  assert.equal(reasonText('unverified_source_quote'), 'The diagnosis could not be matched to your slide');
  assert.equal(reasonText('unsupported_claims'), 'Many statements lacked supporting evidence on the page');
  assert.equal(reasonText('all_models_failed'), 'Every AI model failed on this item');
  assert.equal(reasonText('no_usable_answer'), 'No model gave a usable answer');
  assert.equal(reasonText('claude_quota'), 'Waiting for Claude quota to finish the check');
  assert.equal(reasonText('soft:low_confidence'), 'Low-confidence diagnosis');
  assert.equal(reasonText('soft:source_doubt'), 'Your source may contradict standard teaching');
  assert.equal(reasonText('soft:context_free_claims'), 'Statements lacked context');
});

test('unknown or prototype-shaped reason codes fall back', () => {
  assert.equal(reasonText('gate_kept_last'), 'Fell short of the quality check');
  assert.equal(reasonText(''), 'Fell short of the quality check');
  assert.equal(reasonText('toString'), 'Fell short of the quality check');
});

test('reason hints fall back for unknown codes', () => {
  assert.match(reasonHint('low_text_coverage'), /own text/);
  assert.match(reasonHint('unverified_source_quote'), /slide/);
  assert.match(reasonHint('all_models_failed'), /yourself/);
  assert.equal(reasonHint('toString'), 'Compare the evidence below with the original page.');
});

test('kind and page labels', () => {
  assert.equal(kindLabel('page'), 'Page');
  assert.equal(kindLabel('figure'), 'Figure');
  assert.equal(kindLabel('notes'), 'Notes');
  assert.equal(pagesLabel(12, 12), 'page 12');
  assert.equal(pagesLabel(14, 15), 'pages 14–15');
  assert.equal(pagesLabel(7, null), 'page 7');
  assert.equal(pagesLabel(null, 9), 'page 9');
  assert.equal(pagesLabel(null, null), '');
  assert.equal(itemPage(14, 15), 14);
  assert.equal(itemPage(null, null), 1);
  assert.equal(itemPage(0, 0), 1);
});

test('isRedList accepts the API shape and rejects drift', () => {
  assert.equal(isRedList({ items: [], flagged_facts: [] }), true);
  assert.equal(isRedList({ items: [item(), item({ page_from: null, page_to: null, kind: 'notes' })], flagged_facts: [fact({ doubt: null })] }), true);
  assert.equal(isRedList(null), false);
  assert.equal(isRedList([]), false);
  assert.equal(isRedList({ items: [] }), false);
  assert.equal(isRedList({ items: [item({ kind: 'table' as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [item({ page_from: '3' as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [], flagged_facts: [fact({ page_from: null as never })] }), false);
  assert.equal(isRedList({ items: [], flagged_facts: [fact({ statement: 5 as never })] }), false);
});

test('isRedList checks the evidence fields', () => {
  const figure = item({ kind: 'figure', figures: [FIGURE] });
  const notes = item({ kind: 'notes', statements: [{ statement: 'S', evidence_span: 'E', status: 'flagged' }] });
  const reviewed = item({ status: 'reviewed', verdict: 'needs_fix', note: 'x' });
  assert.equal(isRedList({ items: [figure, notes, reviewed], flagged_facts: [] }), true);
  assert.equal(isRedList({ items: [item({ verdict: 'maybe' as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [item({ status: 'open' as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [item({ figures: [{ ...FIGURE, has_image: 'yes' }] as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [item({ statements: [{ statement: 1 }] as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [item({ own_text: 3 as never })], flagged_facts: [] }), false);
  assert.equal(isRedList({ items: [], flagged_facts: [fact({ file_name: undefined as never })] }), false);
});

test('isSummary accepts the summary shape and rejects drift', () => {
  assert.equal(isSummary([]), true);
  assert.equal(isSummary([summary(), summary({ reasons: {} })]), true);
  assert.equal(isSummary({}), false);
  assert.equal(isSummary([summary({ open_pages: -1 })]), false);
  assert.equal(isSummary([summary({ reviewed: '2' as never })]), false);
  assert.equal(isSummary([summary({ reasons: { x: 'many' } as never })]), false);
  assert.equal(isSummary([summary({ file_name: null as never })]), false);
});

test('counts, labels and top reasons', () => {
  assert.equal(redCount(null), 0);
  assert.equal(redCount({ items: [item(), item()], flagged_facts: [fact()] }), 3);
  assert.equal(summaryCount([]), 0);
  const small = summary({ open_pages: 1, open_figures: 0, open_notes: 0, open_facts: 0 });
  assert.equal(summaryCount([summary(), small]), 63);
  assert.equal(countsLabel(summary()), '12 pages · 3 figures · 40 note sections · 7 facts');
  assert.equal(countsLabel(summary({ open_pages: 1, open_figures: 0, open_notes: 1, open_facts: 0 })), '1 page · 1 note section');
  assert.equal(countsLabel(summary({ open_pages: 0, open_figures: 0, open_notes: 0, open_facts: 0 })), '');
  assert.deepEqual(topReasons(summary().reasons, 2), [
    ['unsupported_claims', 40],
    ['low_text_coverage', 10]
  ]);
});

test('items sort by page with unknown pages last', () => {
  const a = item({ id: 'a', page_from: 9 });
  const b = item({ id: 'b', page_from: null, page_to: null });
  const c = item({ id: 'c', page_from: 2 });
  assert.deepEqual(sortByPage([a, b, c]).map((i) => i.id), ['c', 'a', 'b']);
});

test('verdict form parsing', () => {
  assert.deepEqual(parseVerdictForm(form([['id', ID], ['verdict', 'needs_fix'], ['note', '  wrong side  ']])), {
    ok: true,
    value: { id: ID, verdict: 'needs_fix', note: 'wrong side' }
  });
  assert.deepEqual(parseVerdictForm(form([['id', ID], ['verdict', 'correct']])), {
    ok: true,
    value: { id: ID, verdict: 'correct', note: '' }
  });
  assert.equal(parseVerdictForm(form([['id', ID], ['verdict', 'remove'], ['note', 'x'.repeat(4000)]])).ok, true);
  assert.equal(parseVerdictForm(form([['id', ID], ['verdict', 'remove'], ['note', 'x'.repeat(4001)]])).ok, false);
  assert.equal(parseVerdictForm(form([['id', ID], ['verdict', 'maybe']])).ok, false);
  assert.equal(parseVerdictForm(form([['id', ID]])).ok, false);
  assert.equal(parseVerdictForm(form([['id', 'nope'], ['verdict', 'correct']])).ok, false);
});

test('fact form parsing validates ids, decisions and notes', () => {
  assert.deepEqual(parseFactForm(form([['id', ID], ['decision', 'keep']])), {
    ok: true,
    value: { id: ID, decision: 'keep', note: '' }
  });
  assert.deepEqual(parseFactForm(form([['id', ID], ['decision', 'reject'], ['note', ' old teaching ']])), {
    ok: true,
    value: { id: ID, decision: 'reject', note: 'old teaching' }
  });
  assert.equal(parseFactForm(form([['id', ID], ['decision', 'keep'], ['note', 'x'.repeat(4001)]])).ok, false);
  assert.equal(parseFactForm(form([['id', ID], ['decision', 'delete']])).ok, false);
  assert.equal(parseFactForm(form([['id', 'x'], ['decision', 'keep']])).ok, false);
});

test('status query parsing defaults to open', () => {
  assert.equal(parseStatus('reviewed'), 'reviewed');
  assert.equal(parseStatus('open'), 'open');
  assert.equal(parseStatus(null), 'open');
  assert.equal(parseStatus('everything'), 'open');
});
