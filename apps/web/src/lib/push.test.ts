import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  base64UrlToBytes,
  fromApiTime,
  isTimeOfDay,
  parseReminderForm,
  toApiTime,
  toEndpoint,
  toSubscriptionBody
} from './push.ts';

test('base64UrlToBytes decodes unpadded base64url', () => {
  assert.deepEqual([...base64UrlToBytes('AQID_-8')], [1, 2, 3, 255, 239]);
});

test('toSubscriptionBody flattens well-formed https subscriptions into the API shape', () => {
  const keys = { p256dh: 'BPk'.repeat(10), auth: 'authsecret' };
  const good = { endpoint: 'https://push.example/abc', keys, expirationTime: null };
  assert.deepEqual(toSubscriptionBody(good, 'UA/1'), {
    endpoint: good.endpoint,
    p256dh: keys.p256dh,
    auth: keys.auth,
    user_agent: 'UA/1'
  });
  assert.equal(toSubscriptionBody({ ...good, endpoint: 'http://push.example/abc' }), null);
  assert.equal(toSubscriptionBody({ ...good, keys: { ...keys, auth: 'short' } }), null);
  assert.equal(toSubscriptionBody({ endpoint: good.endpoint }), null);
  assert.equal(toSubscriptionBody('nope'), null);
  assert.equal(toEndpoint({ endpoint: good.endpoint }), good.endpoint);
  assert.equal(toEndpoint({}), null);
});

test('reminder times convert between the time input and the API', () => {
  assert.equal(fromApiTime('07:30:00'), '07:30');
  assert.equal(fromApiTime(null), '19:00');
  assert.equal(toApiTime('07:30'), '07:30:00');
  assert.equal(toApiTime('7:30'), null);
});

test('parseReminderForm builds the full settings body', () => {
  const form = new FormData();
  form.set('enabled', 'on');
  form.set('reminder_time', '06:45');
  form.set('timezone', 'Asia/Karachi');
  form.append('channels', 'push');
  form.append('channels', 'sms');
  form.set('include_plan', 'on');
  assert.deepEqual(parseReminderForm(form), {
    ok: true,
    settings: {
      enabled: true,
      reminder_time: '06:45:00',
      timezone: 'Asia/Karachi',
      channels: ['push'],
      include_due_cards: false,
      include_plan: true
    }
  });
  form.set('reminder_time', '25:00');
  assert.equal(parseReminderForm(form).ok, false);
});

test('isTimeOfDay validates HH:MM', () => {
  assert.equal(isTimeOfDay('07:30'), true);
  assert.equal(isTimeOfDay('23:59'), true);
  assert.equal(isTimeOfDay('24:00'), false);
  assert.equal(isTimeOfDay('7:30'), false);
});
