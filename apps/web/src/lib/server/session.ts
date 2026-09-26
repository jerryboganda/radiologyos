// Today session and progress-insights API client (apps/api/app/api/study_sessions.py).
import { fail, type RequestEvent } from '@sveltejs/kit';
import { isUuid } from '$lib/citations';
import { parseAnswerForm, parseStepRef } from '$lib/session';
import type { Insights, StepAnswerIn, StudySession } from '$lib/types/session';
import { failureMessage, getJson, sendJson } from './client';

/** 409 until a profile exists. Builds today's session once, then resumes it. */
export const getTodaySession = (event: RequestEvent) => getJson<StudySession>(event, '/v1/study/sessions/today');

/** 409 until a profile exists. */
export const getInsights = (event: RequestEvent) => getJson<Insights>(event, '/v1/study/insights');

const stepPath = (sessionId: string, stepNo: number, action: string) =>
  `/v1/study/sessions/${encodeURIComponent(sessionId)}/steps/${stepNo}/${action}`;

export const startStep = (event: RequestEvent, sessionId: string, stepNo: number) =>
  sendJson<StudySession>(event, stepPath(sessionId, stepNo, 'start'), 'POST');

export const completeStep = (event: RequestEvent, sessionId: string, stepNo: number, skip = false) =>
  sendJson<StudySession>(event, `${stepPath(sessionId, stepNo, 'complete')}${skip ? '?skip=true' : ''}`, 'POST');

export const answerStep = (event: RequestEvent, sessionId: string, stepNo: number, body: StepAnswerIn) =>
  sendJson<StudySession>(event, stepPath(sessionId, stepNo, 'answer'), 'POST', body);

export const completeSession = (event: RequestEvent, sessionId: string) =>
  sendJson<StudySession>(event, `/v1/study/sessions/${encodeURIComponent(sessionId)}/complete`, 'POST');

/** Form actions for the Today runner; each answers `{ section: 'session', ... }`. */
export const sessionActions = {
  stepStart: async (event: RequestEvent) => {
    const ref = parseStepRef(await event.request.formData());
    if (!ref.ok) return fail(400, { section: 'session', error: ref.error });
    const result = await startStep(event, ref.value.sessionId, ref.value.stepNo);
    if (result.state !== 'ok') return fail(400, { section: 'session', error: failureMessage(result) });
    return { section: 'session', step: ref.value.stepNo };
  },
  stepComplete: async (event: RequestEvent) => {
    const form = await event.request.formData();
    const ref = parseStepRef(form);
    if (!ref.ok) return fail(400, { section: 'session', error: ref.error });
    const result = await completeStep(event, ref.value.sessionId, ref.value.stepNo, form.get('skip') === 'true');
    if (result.state !== 'ok') return fail(400, { section: 'session', error: failureMessage(result) });
    return { section: 'session', step: result.data.current_step };
  },
  stepAnswer: async (event: RequestEvent) => {
    const form = await event.request.formData();
    const ref = parseStepRef(form);
    if (!ref.ok) return fail(400, { section: 'session', error: ref.error });
    const body = parseAnswerForm(form);
    if (!body.ok) return fail(400, { section: 'session', error: body.error });
    const result = await answerStep(event, ref.value.sessionId, ref.value.stepNo, body.value);
    if (result.state !== 'ok') return fail(400, { section: 'session', error: failureMessage(result) });
    return { section: 'session', step: ref.value.stepNo };
  },
  sessionComplete: async (event: RequestEvent) => {
    const sessionId = String((await event.request.formData()).get('session_id') ?? '');
    if (!isUuid(sessionId)) return fail(400, { section: 'session', error: 'Unknown session.' });
    const result = await completeSession(event, sessionId);
    if (result.state !== 'ok') return fail(400, { section: 'session', error: failureMessage(result) });
    return { section: 'session', completed: true };
  }
};
