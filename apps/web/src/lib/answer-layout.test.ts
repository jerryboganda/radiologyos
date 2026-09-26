import assert from 'node:assert/strict';
import { test } from 'node:test';
import { layoutAnswer, quizHref } from './answer-layout.ts';
import type { Segment } from './types/tutor.ts';

const CITE = [{ kind: 'source' as const, label: 'S1', chunk_id: 'c1', page_from: 1, page_to: 1 }];

function seg(text: string, extra: Partial<Segment> = {}): Segment {
  return { text, origin: 'sources', citations: CITE, ...extra };
}

test('plain segments stay prose', () => {
  const blocks = layoutAnswer([seg('A.'), seg('B.')]);
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ['text', 'text']
  );
});

test('a comparison becomes one table with cells in column order', () => {
  const blocks = layoutAnswer([
    seg('Fat.', { row: 'Content', column: 'Dermoid' }),
    seg('CSF-like.', { row: 'Content', column: 'Epidermoid' }),
    seg('Restricts.', { row: 'DWI', column: 'Epidermoid' }),
    seg('Fat is the key.')
  ]);
  assert.equal(blocks.length, 2);
  const table = blocks[0];
  assert.equal(table.kind, 'table');
  if (table.kind !== 'table') return;
  assert.deepEqual(table.columns, ['Dermoid', 'Epidermoid']);
  assert.deepEqual(
    table.rows.map((r) => r.label),
    ['Content', 'DWI']
  );
  assert.deepEqual(table.rows[1].cells[0], []); // DWI of a dermoid is not covered
  assert.equal(table.rows[1].cells[1][0].text, 'Restricts.');
  assert.equal(blocks[1].kind, 'text');
});

test('sections become headings and a row without a column stays prose', () => {
  const blocks = layoutAnswer([
    seg('F1 shows it.', { section: 'Figures' }),
    seg('Key point.', { section: 'Key points', row: 'orphan' }),
    seg('Another.', { section: 'Key points' })
  ]);
  assert.deepEqual(
    blocks.map((b) => (b.kind === 'heading' ? `h:${b.text}` : b.kind)),
    ['h:Figures', 'text', 'h:Key points', 'text', 'text']
  );
});

test('web segments never form table cells or headings', () => {
  const web = { text: 'W.', origin: 'web' as const, citations: [{ kind: 'web' as const, url: 'https://radiopaedia.org/a' }] };
  const blocks = layoutAnswer([{ ...web, row: 'r', column: 'c', section: 'S' }]);
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ['text']
  );
});

test('quiz hand-off links to question generation with the topic', () => {
  assert.equal(quizHref(' renal masses '), '/questions?topic=renal%20masses');
  assert.equal(quizHref('a&b').includes('&b'), false);
});
