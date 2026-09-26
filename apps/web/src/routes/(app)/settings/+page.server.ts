import { fail, type RequestEvent } from '@sveltejs/kit';
import { dataOr, isKind, loadProblem, type ApiResult } from '$lib/api-state';
import { isAdminRole } from '$lib/admin-usage';
import { parseDeleteForm } from '$lib/data-rights';
import { confirmsQuota } from '$lib/pipeline-control';
import { parseReminderForm } from '$lib/push';
import {
  approvePipeline,
  dismissPipeline,
  loadModelUsageCard,
  loadPipelineCard,
  loadUsageCard,
  pausePipeline,
  resumePipeline
} from '$lib/server/admin';
import { failureMessage } from '$lib/server/client';
import { deleteAccount, listExports, requestExport } from '$lib/server/data-rights';
import { getSettings, getVapidKey, saveSettings } from '$lib/server/notifications';
import { getProfile, saveProfile } from '$lib/server/study';
import { parseProfileForm } from '$lib/study';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  event.depends('app:exports');
  const [profile, settings, vapid, exports, usageCard, modelUsageCard, pipelineCard] = await Promise.all([
    getProfile(event),
    getSettings(event),
    getVapidKey(event),
    listExports(event),
    loadUsageCard(event),
    loadModelUsageCard(event),
    loadPipelineCard(event)
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
    modelUsageCard,
    pipelineCard
  };
};

const PIPELINE = 'pipeline';

/** Run an admin-only pipeline call; the API also enforces the role (403). */
async function pipelineAction<T>(event: RequestEvent, call: (event: RequestEvent) => Promise<ApiResult<T>>, message: (data: T) => string) {
  if (!isAdminRole(event.locals.user?.tenantRole)) return fail(403, { section: PIPELINE, error: 'Only an admin can control library processing.' });
  const result = await call(event);
  if (result.state !== 'ok') return fail(isKind(result, 'forbidden') ? 403 : 400, { section: PIPELINE, error: failureMessage(result) });
  return { section: PIPELINE, message: message(result.data) };
}

export const actions: Actions = {
  pausePipeline: (event) => pipelineAction(event, pausePipeline, () => 'Paused. Work stops after the item in progress is saved.'),
  resumePipeline: (event) => pipelineAction(event, resumePipeline, () => 'Resumed. Processing continues where it stopped.'),
  approvePipeline: async (event) => {
    if (!confirmsQuota(await event.request.formData())) {
      return fail(400, { section: PIPELINE, error: 'Tick the box to confirm this uses your Claude quota.' });
    }
    return pipelineAction(event, approvePipeline, () => 'Approved. Claude Opus will work through the waiting items.');
  },
  dismissPipeline: (event) =>
    pipelineAction(event, dismissPipeline, (data) => `Dismissed ${data.dismissed} item${data.dismissed === 1 ? '' : 's'} without using Claude.`),
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
