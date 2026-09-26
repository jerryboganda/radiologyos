// Notifications API client (apps/api/app/api/notifications.py).
import type { RequestEvent } from '@sveltejs/kit';
import type { NotificationSettings, SubscriptionIn, TestPushResult, VapidKey } from '$lib/types/settings';
import { getJson, sendJson } from './client';

const N = '/v1/notifications';

/** Defaults are returned until the user saves settings for the first time. */
export const getSettings = (event: RequestEvent) => getJson<NotificationSettings>(event, `${N}/settings`);

export const saveSettings = (event: RequestEvent, settings: NotificationSettings) =>
  sendJson<NotificationSettings>(event, `${N}/settings`, 'PUT', settings);

/** Public by design; the private key never leaves the API. */
export const getVapidKey = (event: RequestEvent) => getJson<VapidKey>(event, `${N}/vapid-public-key`);

/** 204 on success. */
export const savePushSubscription = (event: RequestEvent, body: SubscriptionIn) =>
  sendJson<void>(event, `${N}/subscriptions`, 'POST', body);

export const deletePushSubscription = (event: RequestEvent, endpoint: string) =>
  sendJson<void>(event, `${N}/subscriptions`, 'DELETE', { endpoint });

/** 202 {sent, removed}; 503 when the server has no VAPID private key. */
export const sendTestPush = (event: RequestEvent) => sendJson<TestPushResult>(event, `${N}/test`, 'POST');
