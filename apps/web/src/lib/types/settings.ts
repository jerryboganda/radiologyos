// Notifications API contract (apps/api/app/api/notifications.py).
export type Channel = 'push' | 'email';

export interface NotificationSettings {
  enabled: boolean;
  /** Local time as "HH:MM:SS" (the API's `time` type). */
  reminder_time: string;
  /** IANA zone; the API rejects unknown zones with 422. */
  timezone: string;
  channels: Channel[];
  include_due_cards: boolean;
  include_plan: boolean;
}

export const DEFAULT_SETTINGS: NotificationSettings = {
  enabled: true,
  reminder_time: '19:00:00',
  timezone: 'Asia/Karachi',
  channels: ['push'],
  include_due_cards: true,
  include_plan: true
};

export interface VapidKey {
  public_key: string | null;
  /** False until the server holds both VAPID keys; push cannot be sent before then. */
  enabled: boolean;
}

/** POST /v1/notifications/subscriptions body (flat keys, not the browser's nested JSON). */
export interface SubscriptionIn {
  endpoint: string;
  p256dh: string;
  auth: string;
  user_agent?: string | null;
}

export interface TestPushResult {
  sent: number;
  removed: number;
}
