// Planned notifications API (/v1/notifications/*).
export interface ReminderPrefs {
  enabled: boolean;
  /** Local time, HH:MM (24 h). */
  time_of_day: string;
  timezone: string;
  /** 0 = Sunday … 6 = Saturday. */
  days: number[];
}

export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export const DEFAULT_REMINDERS: ReminderPrefs = {
  enabled: false,
  time_of_day: '19:00',
  timezone: 'UTC',
  days: [0, 1, 2, 3, 4, 5, 6]
};
