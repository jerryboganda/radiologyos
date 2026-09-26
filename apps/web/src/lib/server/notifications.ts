// Notifications API client (planned: /v1/notifications/*).
import type { RequestEvent } from '@sveltejs/kit';
import type { PushSubscriptionBody, ReminderPrefs } from '$lib/types/settings';
import { getJson, sendJson } from './client';

export const getReminders = (event: RequestEvent) =>
  getJson<ReminderPrefs>(event, '/v1/notifications/preferences');

export const saveReminders = (event: RequestEvent, prefs: ReminderPrefs) =>
  sendJson<ReminderPrefs>(event, '/v1/notifications/preferences', 'PUT', prefs);

/** VAPID public key (public by design; the private key never leaves the API). */
export const getVapidKey = (event: RequestEvent) =>
  getJson<{ public_key: string }>(event, '/v1/notifications/vapid-public-key');

export const savePushSubscription = (event: RequestEvent, body: PushSubscriptionBody) =>
  sendJson<unknown>(event, '/v1/notifications/push-subscriptions', 'POST', body);

export const deletePushSubscription = (event: RequestEvent, endpoint: string) =>
  sendJson<unknown>(event, '/v1/notifications/push-subscriptions', 'DELETE', { endpoint });

export const sendTestPush = (event: RequestEvent) =>
  sendJson<unknown>(event, '/v1/notifications/test', 'POST');
