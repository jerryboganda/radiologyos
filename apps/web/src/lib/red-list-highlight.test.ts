import assert from 'node:assert/strict';
import { test } from 'node:test';
import { highlight } from './red-list.ts';

const marked = (text: string, spans: string[]) =>
  highlight(text, spans)
    .filter((s) => s.mark)
    .map((s) => s.text);

test('slices always rebuild the original text', () => {
  const text = 'Right  lower\nlobe consolidation with AIR bronchograms.';
  const segments = highlight(text, ['lower lobe', 'air bronchograms']);
  assert.equal(segments.map((s) => s.text).join(''), text);
  assert.deepEqual(marked(text, ['lower lobe', 'air bronchograms']), ['lower\nlobe', 'AIR bronchograms']);
});

test('case-insensitive and whitespace-tolerant', () => {
  assert.deepEqual(marked('Ground-glass\t\topacity', ['GROUND-GLASS OPACITY']), ['Ground-glass\t\topacity']);
  assert.deepEqual(marked('a b  c d', ['  b c  ']), ['b  c']);
});

test('every occurrence is marked', () => {
  assert.deepEqual(marked('cyst, cyst and cyst', ['cyst']), ['cyst', 'cyst', 'cyst']);
});

test('overlapping and touching ranges merge', () => {
  const text = 'the pleural effusion is large';
  assert.deepEqual(marked(text, ['pleural eff', 'effusion is']), ['pleural effusion is']);
  assert.deepEqual(marked(text, ['the pl', 'eural']), ['the pleural']);
  assert.deepEqual(marked(text, ['pleural', ' effusion ']), ['pleural', 'effusion']);
  assert.deepEqual(marked(text, ['effusion', 'pleural effusion is large']), ['pleural effusion is large']);
});

test('empty, short, missing and odd inputs never throw', () => {
  assert.deepEqual(highlight('', ['abc']), []);
  assert.deepEqual(highlight('plain text', []), [{ text: 'plain text', mark: false }]);
  assert.deepEqual(highlight('plain text', ['', '  ', 'ai', 'xyz']), [{ text: 'plain text', mark: false }]);
  assert.deepEqual(highlight('plain text', null as never), [{ text: 'plain text', mark: false }]);
  assert.deepEqual(highlight('plain text', [null, 5] as never), [{ text: 'plain text', mark: false }]);
  assert.deepEqual(highlight(null as never, ['abc']), []);
  assert.deepEqual(marked('a.*+?(b)[c]', ['.*+?(b)[']), ['.*+?(b)[']);
});

test('surrounding whitespace stays unmarked', () => {
  assert.deepEqual(highlight('  Whole  ', ['whole']), [
    { text: '  ', mark: false },
    { text: 'Whole', mark: true },
    { text: '  ', mark: false }
  ]);
});
