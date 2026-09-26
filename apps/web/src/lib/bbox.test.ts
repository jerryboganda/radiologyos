import assert from 'node:assert/strict';
import { test } from 'node:test';
import { bboxCenter, bboxToStyle, parseBBox } from './bbox.ts';

test('bboxToStyle renders normalised boxes as percentages', () => {
  assert.equal(bboxToStyle([0.1, 0.2, 0.5, 0.6]), 'left:10%;top:20%;width:40%;height:40%');
});

test('bboxToStyle keeps sub-percent precision without float noise', () => {
  assert.equal(bboxToStyle([0.1234, 0, 0.3, 0.0005]), 'left:12.34%;top:0%;width:17.66%;height:0.05%');
});

test('parseBBox clamps to the page and orders corners', () => {
  assert.deepEqual(parseBBox([1.2, 0.9, -0.1, 0.1]), [0, 0.1, 1, 0.9]);
});

test('invalid boxes are rejected', () => {
  assert.equal(parseBBox(null), null);
  assert.equal(parseBBox([0, 0, 1]), null);
  assert.equal(parseBBox([0, 0, 'x', 1]), null);
  assert.equal(parseBBox([0, 0, Number.NaN, 1]), null);
  assert.equal(bboxToStyle([0.5, 0.5, 0.5, 0.9]), null);
});

test('bboxCenter maps to rendered pixels', () => {
  assert.deepEqual(bboxCenter([0, 0, 0.5, 0.5], 1000, 2000), { x: 250, y: 500 });
  assert.equal(bboxCenter('nope', 10, 10), null);
});
