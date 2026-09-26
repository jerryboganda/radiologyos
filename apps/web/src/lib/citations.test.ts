import assert from 'node:assert/strict';
import { test } from 'node:test';
import { citationHref, citationLabel, isUuid, readerHref, safeWebUrl, webHost } from './citations.ts';

const SOURCE = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';

test('readerHref builds a page and block deep link', () => {
  assert.equal(readerHref(SOURCE, 12, 4), `/library/${SOURCE}?page=12&block=4`);
  assert.equal(readerHref(SOURCE, 3), `/library/${SOURCE}?page=3`);
  assert.equal(readerHref(SOURCE, 3, 0), `/library/${SOURCE}?page=3&block=0`);
});

test('readerHref falls back to page 1 for invalid pages and drops invalid blocks', () => {
  assert.equal(readerHref(SOURCE, 0, -1), `/library/${SOURCE}?page=1`);
  assert.equal(readerHref(SOURCE, 2.5, 1.5), `/library/${SOURCE}?page=1`);
});

test('citationLabel formats single pages and ranges', () => {
  assert.equal(citationLabel({ source_title: 'Grainger', page_from: 3, page_to: 3 }), 'Grainger · p.3');
  assert.equal(citationLabel({ source_title: 'Grainger', page_from: 3, page_to: 5 }), 'Grainger · p.3–5');
  assert.equal(citationLabel({ source_title: '  ', page_from: 1, page_to: 1 }), 'Untitled source · p.1');
});

test('citationHref links to the first cited block', () => {
  const citation = {
    source_id: SOURCE,
    source_title: 'Notes',
    page_from: 7,
    page_to: 8,
    block_refs: [{ page: 7, block: 2 }, { page: 8, block: 0 }]
  };
  assert.equal(citationHref(citation), `/library/${SOURCE}?page=7&block=2`);
  assert.equal(citationHref({ ...citation, block_refs: [] }), `/library/${SOURCE}?page=7`);
});

test('only http(s) web citations are allowed', () => {
  assert.equal(safeWebUrl('https://radiopaedia.org/articles/x'), 'https://radiopaedia.org/articles/x');
  assert.equal(safeWebUrl('javascript:alert(1)'), null);
  assert.equal(safeWebUrl('not a url'), null);
  assert.equal(webHost('https://www.radiopaedia.org/a'), 'radiopaedia.org');
});

test('isUuid validates route parameters', () => {
  assert.equal(isUuid(SOURCE), true);
  assert.equal(isUuid('../etc'), false);
});
