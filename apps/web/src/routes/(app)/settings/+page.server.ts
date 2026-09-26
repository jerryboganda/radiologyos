import { env } from '$env/dynamic/private';
import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { parseDeleteForm } from '$lib/data-rights';
import { parseReminderForm } from '$lib/push';
import { loadUsageCard } from '$lib/server/admin';
import { failureMessage } from '$lib/server/client';
import { deleteAccount, listExports, requestExport } from '$lib/server/data-rights';
import { getSettings, getVapidKey, saveSettings } from '$lib/server/notifications';
import { getProfile, saveProfile } from '$lib/server/study';
import { parseProfileForm } from '$lib/study';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  event.depends('app:exports');
  const [profile, settings, vapid, exports, usageCard] = await Promise.all([
    getProfile(event),
    getSettings(event),
    getVapidKey(event),
    listExports(event),
    loadUsageCard(event)
  ]);
  return {
    profile: dataOr(profile, null),
    settings: dataOr(settings, null),
    settingsProblem: loadProblem(settings),
    vapidKey: vapid.state === 'ok' ? vapid.data.public_key : null,
    pushEnabled: vapid.state === 'ok' && vapid.data.enabled,
    exports: dataOr(exports, []),
    exportsProblem: loadProblem(exports),
    usageCard,
    previewEnabled: env.PREVIEW_ENABLED === 'true'
  };
};

export const actions: Actions = {
  profile: async (event) => {
    const form = await event.request.formData();
    const existing = await getProfile(event);
    const parsed = parseProfileForm(form, dataOr(existing, null));
    if (!parsed.ok) return fail(400, { section: 'profile', error: parsed.error });
    const result = await saveProfile(event, parsed.profile);
    if (result.state !== 'ok') return fail(400, { section: 'profile', error: failureMessage(result) });
    return { section: 'profile', saved: true };
  },
  reminders: async (event) => {
    const parsed = parseReminderForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'reminders', error: parsed.error });
    const result = await saveSettings(event, parsed.settings);
    if (result.state !== 'ok') return fail(400, { section: 'reminders', error: failureMessage(result) });
    return { section: 'reminders', saved: true };
  },
  export: async (event) => {
    const result = await requestExport(event);
    if (result.state !== 'ok') return fail(400, { section: 'export', error: failureMessage(result) });
    return { section: 'export', message: 'Export queued. It appears below when it is ready to download.' };
  },
  deleteAccount: async (event) => {
    const parsed = parseDeleteForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'delete', error: parsed.error });
    const result = await deleteAccount(event, parsed.value.confirmation);
    if (result.state !== 'ok') return fail(400, { section: 'delete', error: failureMessage(result) });
    return { section: 'delete', deletionQueued: true };
  }
};
