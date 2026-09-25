import assert from 'node:assert/strict';
import test from 'node:test';
import { previewUserId } from './preview-identity.ts';

test('preview identity is stable and subject-specific', () => {
  const first = previewUserId('provider|subject-a');
  assert.equal(first, previewUserId('provider|subject-a'));
  assert.notEqual(first, previewUserId('provider|subject-b'));
  assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
});
