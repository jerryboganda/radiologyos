import assert from 'node:assert/strict';
import { test } from 'node:test';
import { base64UrlToBytes, isTimeOfDay, toSubscriptionBody } from './push.ts';

test('base64UrlToBytes decodes unpadded base64url', () => {
  assert.deepEqual([...base64UrlToBytes('AQID_-8')], [1, 2, 3, 255, 239]);
});

test('toSubscriptionBody accepts only well-formed https subscriptions', () => {
  const good = { endpoint: 'https://push.example/abc', keys: { p256dh: 'BPk', auth: 'xyz' }, expirationTime: null };
  assert.deepEqual(toSubscriptionBody(good), { endpoint: good.endpoint, keys: good.keys });
  assert.equal(toSubscriptionBody({ ...good, endpoint: 'http://push.example/abc' }), null);
  assert.equal(toSubscriptionBody({ endpoint: good.endpoint }), null);
  assert.equal(toSubscriptionBody('nope'), null);
});

test('isTimeOfDay validates HH:MM', () => {
  assert.equal(isTimeOfDay('07:30'), true);
  assert.equal(isTimeOfDay('23:59'), true);
  assert.equal(isTimeOfDay('24:00'), false);
  assert.equal(isTimeOfDay('7:30'), false);
});
