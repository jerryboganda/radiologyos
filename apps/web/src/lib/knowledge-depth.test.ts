import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ddxTree, footnotes, noteBadge, noteSections } from './concept-note.ts';
import { nextFocus, radialLayout, shortLabel } from './graph-layout.ts';
import { parseMergeForm, parseTrustForm, parseVerifyForm } from './knowledge.ts';
import type { ClaimOut, EdgeOut, NoteBody, NoteState } from './types/knowledge.ts';

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(entries)) data.append(name, value);
  return data;
}

const BODY: NoteBody = {
  definition: [{ text: 'PAP fills alveoli.', claim_ids: [ID(1)] }],
  imaging: [{ modality: 'HRCT', sentences: [{ text: 'Crazy paving.', claim_ids: [ID(2), ID(1)] }] }],
  differentials: [{ name: 'Pulmonary oedema', concept_id: ID(9), discriminators: [{ text: 'Effusions.', claim_ids: [ID(3)] }] }],
  pearls: [],
  pitfalls: []
};

const claim = (n: number): ClaimOut => ({
  id: ID(n),
  claim_type: 'definition',
  statement: `Claim ${n}`,
  evidence_span: 'span',
  status: 'active',
  verification: 'single_source',
  importance: 3,
  modality: '',
  citation: { source_id: ID(50), page_from: 1, page_to: 1 },
  supporting: [],
  agent_version: 'knowledge_extract/v1'
});

const edge = (n: number, relation: string, name: string): EdgeOut => ({
  id: ID(100 + n),
  relation,
  direction: 'out',
  other_id: ID(n),
  other_name: name,
  citation: {}
});

test('note sections skip empty ones and footnotes number claims by first use', () => {
  assert.deepEqual(noteSections(BODY).map((s) => s.key), ['definition', 'imaging']);
  const { numbers, list } = footnotes(BODY, [claim(1), claim(2)]);
  assert.deepEqual([...numbers.entries()], [[ID(1), 1], [ID(2), 2], [ID(3), 3]]);
  assert.equal(list[2].claim, null); // a claim no longer visible is shown as unavailable
  assert.equal(list[0].claim?.statement, 'Claim 1');
});

test('the DDx tree adds graph differentials the note did not cover, once', () => {
  const edges = [edge(9, 'differential_of', 'Pulmonary oedema'), edge(10, 'differential_of', 'Sarcoidosis'), edge(11, 'sign_of', 'Honeycombing')];
  const tree = ddxTree(BODY, edges);
  assert.deepEqual(tree.map((b) => [b.name, b.fromGraph]), [['Pulmonary oedema', false], ['Sarcoidosis', true]]);
  assert.deepEqual(ddxTree(null, edges).map((b) => b.name), ['Pulmonary oedema', 'Sarcoidosis']);
});

test('the note badge never claims more trust than the state allows', () => {
  const base: NoteState = { concept_id: ID(1), state: 'current', open_conflicts: 0, verifiable: true, note: null };
  const note = { id: ID(7), version: 2, status: 'draft' as const, body: BODY, sentences: 3, dropped: 1, agent_version: 'v1', verified_at: null, created_at: '' };
  assert.equal(noteBadge(base).tone, 'muted');
  assert.equal(noteBadge({ ...base, note }).label, 'Draft · every sentence cited');
  assert.equal(noteBadge({ ...base, note, open_conflicts: 1 }).tone, 'warn');
  assert.equal(noteBadge({ ...base, note, state: 'stale' }).tone, 'warn');
  assert.equal(noteBadge({ ...base, note: { ...note, status: 'verified' } }).tone, 'ok');
  assert.equal(noteBadge({ ...base, state: 'stale', note: { ...note, status: 'verified' } }).label, 'Out of date: claims changed');
});

test('radial layout centres the concept, rings neighbours, and drops strays', () => {
  const nodes = [
    { id: 'c', name: 'Centre', concept_type: 'disease', depth: 0 },
    { id: 'a', name: 'Alpha', concept_type: 'sign', depth: 1 },
    { id: 'b', name: 'Beta', concept_type: 'sign', depth: 1 },
    { id: 'x', name: 'Two hops away from the centre concept', concept_type: 'finding', depth: 2 },
    { id: 'z', name: 'Unreachable', concept_type: 'finding', depth: 2 }
  ];
  const edges = [
    { source: 'a', target: 'c', relation: 'sign_of' },
    { source: 'b', target: 'c', relation: 'sign_of' },
    { source: 'x', target: 'a', relation: 'associated_with' },
    { source: 'q', target: 'c', relation: 'is_a' }
  ];
  const layout = radialLayout('c', nodes, edges, 400);
  const at = new Map(layout.nodes.map((n) => [n.id, n]));
  assert.deepEqual([at.get('c')?.x, at.get('c')?.y], [200, 200]);
  assert.ok(!at.has('z'));
  assert.equal(layout.edges.length, 3);
  const dist = (id: string) => Math.hypot((at.get(id)?.x ?? 0) - 200, (at.get(id)?.y ?? 0) - 200);
  assert.ok(dist('x') > dist('a'));
  assert.ok(at.get('x')!.label.endsWith('…') && at.get('x')!.label.length <= 22);
  assert.deepEqual(radialLayout('missing', nodes, edges).nodes, []);
  assert.equal(shortLabel('  Short  '), 'Short');
});

test('arrow keys rove focus around the graph', () => {
  assert.equal(nextFocus(0, 'ArrowRight', 3), 1);
  assert.equal(nextFocus(0, 'ArrowLeft', 3), 2);
  assert.equal(nextFocus(2, 'ArrowDown', 3), 0);
  assert.equal(nextFocus(1, 'End', 3), 2);
  assert.equal(nextFocus(1, 'Tab', 3), 1);
  assert.equal(nextFocus(0, 'ArrowRight', 0), -1);
});

test('trust, merge and verify forms validate before calling the API', () => {
  assert.deepEqual(parseTrustForm(form({ conflict_id: ID(1), trust: 'both', note: ' newer edition ' })), {
    ok: true,
    value: { conflictId: ID(1), body: { trust: 'both', note: 'newer edition' } }
  });
  assert.equal(parseTrustForm(form({ conflict_id: ID(1), trust: 'c' })).ok, false);
  assert.equal(parseTrustForm(form({ conflict_id: 'nope', trust: 'a' })).ok, false);
  assert.equal(parseTrustForm(form({ conflict_id: ID(1), trust: 'a', note: 'x'.repeat(1001) })).ok, false);
  assert.deepEqual(parseMergeForm(form({ merge_id: ID(2), action: 'undo' })), { ok: true, value: { mergeId: ID(2), action: 'undo' } });
  assert.equal(parseMergeForm(form({ merge_id: ID(2), action: 'delete' })).ok, false);
  assert.deepEqual(parseVerifyForm(form({ note_id: ID(3) })), { ok: true, value: { noteId: ID(3) } });
  assert.equal(parseVerifyForm(form({})).ok, false);
});
