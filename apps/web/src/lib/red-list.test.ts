import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isRedList, itemPage, kindLabel, pagesLabel, parseFactForm, parseReviewedForm, reasonText, redCount } from './red-list.ts';
import type { FlaggedFact, RedItem } from './types/red-list.ts';

const ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';
const SRC = '9b1c2d3e-4f5a-4b6c-8d7e-0f1a2b3c4d5e';

function item(overrides: Partial<RedItem> = {}): RedItem {
  return {
    id: ID,
    source_id: SRC,
    source_title: 'Chest imaging',
    kind: 'page',
    page_from: 12,
    page_to: 12,
    reason: 'low_text_coverage',
    created_at: '2026-09-27T08:00:00Z',
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
    page_from: 3,
    page_to: 4,
    ...overrides
  };
}

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

test('redCount adds both lists', () => {
  assert.equal(redCount(null), 0);
  assert.equal(redCount({ items: [item(), item()], flagged_facts: [fact()] }), 3);
});

test('form parsing validates ids and decisions', () => {
  assert.deepEqual(parseReviewedForm(form([['id', ID]])), { ok: true, value: { id: ID } });
  assert.equal(parseReviewedForm(form([['id', 'nope']])).ok, false);
  assert.equal(parseReviewedForm(form([])).ok, false);
  assert.deepEqual(parseFactForm(form([['id', ID], ['decision', 'keep']])), { ok: true, value: { id: ID, decision: 'keep' } });
  assert.deepEqual(parseFactForm(form([['id', ID], ['decision', 'reject']])), { ok: true, value: { id: ID, decision: 'reject' } });
  assert.equal(parseFactForm(form([['id', ID], ['decision', 'delete']])).ok, false);
  assert.equal(parseFactForm(form([['id', 'x'], ['decision', 'keep']])).ok, false);
});
