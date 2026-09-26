// Web Push and reminder-settings helpers. Pure for node --test.
import type { Channel, NotificationSettings, SubscriptionIn } from './types/settings';

/** Decode a base64url VAPID public key into the bytes PushManager expects. */
export function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=');
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * Validate a browser PushSubscription JSON (`{endpoint, keys: {p256dh, auth}}`)
 * and flatten it into the API's SubscriptionIn shape, within the API's limits.
 */
export function toSubscriptionBody(value: unknown, userAgent: string | null = null): SubscriptionIn | null {
  if (!value || typeof value !== 'object') return null;
  const { endpoint, keys } = value as { endpoint?: unknown; keys?: { p256dh?: unknown; auth?: unknown } };
  if (typeof endpoint !== 'string' || !endpoint.startsWith('https://') || endpoint.length > 2047) return null;
  if (!keys || typeof keys.p256dh !== 'string' || typeof keys.auth !== 'string') return null;
  if (keys.p256dh.length < 16 || keys.p256dh.length > 255) return null;
  if (keys.auth.length < 8 || keys.auth.length > 127) return null;
  return { endpoint, p256dh: keys.p256dh, auth: keys.auth, user_agent: userAgent ? userAgent.slice(0, 300) : null };
}

/** The endpoint alone, for unsubscribe. */
export function toEndpoint(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const { endpoint } = value as { endpoint?: unknown };
  return typeof endpoint === 'string' && endpoint.length <= 2047 ? endpoint : null;
}

/** "HH:MM" 24-hour validation for reminder times. */
export function isTimeOfDay(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/** "19:00:00" (API) → "19:00" (<input type=time>). */
export function fromApiTime(value: string | null | undefined): string {
  const match = /^(\d{2}):(\d{2})/.exec(value ?? '');
  return match ? `${match[1]}:${match[2]}` : '19:00';
}

/** "19:00" → "19:00:00"; null when invalid. */
export function toApiTime(value: string): string | null {
  return isTimeOfDay(value) ? `${value}:00` : null;
}

export type SettingsParse = { ok: true; settings: NotificationSettings } | { ok: false; error: string };

export function parseReminderForm(form: FormData): SettingsParse {
  const time = toApiTime(String(form.get('reminder_time') ?? ''));
  if (!time) return { ok: false, error: 'Choose a reminder time.' };
  const timezone = String(form.get('timezone') ?? '').trim();
  if (!timezone || timezone.length > 64) return { ok: false, error: 'Your time zone could not be detected.' };
  const channels = [...new Set(form.getAll('channels').map(String))].filter(
    (c): c is Channel => c === 'push' || c === 'email'
  );
  return {
    ok: true,
    settings: {
      enabled: form.get('enabled') === 'on',
      reminder_time: time,
      timezone,
      channels,
      include_due_cards: form.get('include_due_cards') === 'on',
      include_plan: form.get('include_plan') === 'on'
    }
  };
}
