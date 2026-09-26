import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cssWidth, fitScale, mediaUrl, parseBlock, parsePage, zoomIn, zoomOut } from './viewer.ts';

const ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';

test('mediaUrl maps API image paths to the private proxy', () => {
  assert.equal(mediaUrl(`/v1/library/sources/${ID}/pages/12/image`), `/media/pages/${ID}/12`);
  assert.equal(mediaUrl(`/v1/library/figures/${ID}/image`), `/media/figures/${ID}`);
  assert.equal(mediaUrl('https://evil.example/x.png'), null);
  assert.equal(mediaUrl(null), null);
});

test('zoom steps move through fixed levels and clamp', () => {
  assert.equal(zoomIn(1), 1.25);
  assert.equal(zoomIn(0.9), 1);
  assert.equal(zoomIn(4), 4);
  assert.equal(zoomOut(1), 0.75);
  assert.equal(zoomOut(0.25), 0.25);
});

test('actual-pixel maths accounts for device pixel ratio', () => {
  assert.equal(fitScale(800, 1600, 2), 1);
  assert.equal(cssWidth(1600, 1, 2), 800);
  assert.equal(fitScale(0, 1600, 1), 1);
});

test('page and block params parse defensively', () => {
  assert.equal(parsePage('7'), 7);
  assert.equal(parsePage('0'), 1);
  assert.equal(parsePage('abc'), 1);
  assert.equal(parseBlock('0'), 0);
  assert.equal(parseBlock('-1'), null);
  assert.equal(parseBlock(null), null);
});
