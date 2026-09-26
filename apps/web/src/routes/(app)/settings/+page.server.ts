import { env } from '$env/dynamic/private';
import { fail } from '@sveltejs/kit';
import { isTimeOfDay } from '$lib/push';
import { failureMessage } from '$lib/server/client';
import { getReminders, getVapidKey, saveReminders } from '$lib/server/notifications';
import { getProfile, saveProfile } from '$lib/server/study';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  const [profile, reminders, vapid] = await Promise.all([getProfile(event), getReminders(event), getVapidKey(event)]);
  return {
    profile: profile.state === 'ok' ? profile.data : null,
    reminders: reminders.state === 'ok' ? reminders.data : null,
    vapidKey: vapid.state === 'ok' ? vapid.data.public_key : null,
    previewEnabled: env.PREVIEW_ENABLED === 'true'
  };
};

export const actions: Actions = {
  profile: async (event) => {
    const form = await event.request.formData();
    const examDate = String(form.get('exam_date') ?? '');
    const minutes = Number(form.get('daily_minutes') ?? 0);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(examDate) || !Number.isFinite(minutes) || minutes < 15 || minutes > 600) {
      return fail(400, { section: 'profile', error: 'Enter an exam date and 15–600 minutes per day.' });
    }
    const exam_name = String(form.get('exam_name') ?? '').slice(0, 120) || null;
    const timezone = String(form.get('timezone') ?? '') || null;
    const result = await saveProfile(event, { exam_date: examDate, daily_minutes: minutes, exam_name, timezone });
    if (result.state !== 'ok') {
      return fail(503, { section: 'profile', error: failureMessage(result, 'The study service is not online yet; not saved.') });
    }
    return { section: 'profile', saved: true };
  },
  reminders: async (event) => {
    const form = await event.request.formData();
    const time = String(form.get('time_of_day') ?? '');
    const days = form.getAll('days').map(Number).filter((d) => Number.isInteger(d) && d >= 0 && d <= 6);
    if (!isTimeOfDay(time)) return fail(400, { section: 'reminders', error: 'Choose a reminder time.' });
    const result = await saveReminders(event, {
      enabled: form.get('enabled') === 'on',
      time_of_day: time,
      timezone: String(form.get('timezone') ?? '') || 'UTC',
      days: [...new Set(days)].sort()
    });
    if (result.state !== 'ok') {
      return fail(503, {
        section: 'reminders',
        error: failureMessage(result, 'Reminder scheduling is not online yet; preferences were not saved.')
      });
    }
    return { section: 'reminders', saved: true };
  }
};
