import { fail } from '@sveltejs/kit';
import { dataOr } from '$lib/api-state';
import { failureMessage, getJson } from '$lib/server/client';
import { getDueCards, getProfile, getToday, reviewCard, saveProfile } from '$lib/server/study';
import { RATINGS, type Rating } from '$lib/types/study';
import type { SourceSummary } from '$lib/types/library';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
  if (!event.locals.user) {
    return { signedIn: false as const, authError: event.url.searchParams.get('auth_error') };
  }
  event.depends('app:today');
  const [profile, today, due, sources] = await Promise.all([
    getProfile(event),
    getToday(event),
    getDueCards(event),
    getJson<SourceSummary[]>(event, '/v1/library/sources')
  ]);
  return {
    signedIn: true as const,
    authError: null,
    studyOnline: profile.state === 'ok' || profile.state === 'error',
    profile: dataOr(profile, null),
    today: dataOr(today, null),
    due: dataOr(due, null),
    sourceCount: sources.state === 'ok' ? sources.data.length : null
  };
};

export const actions: Actions = {
  onboard: async (event) => {
    const form = await event.request.formData();
    const examDate = String(form.get('exam_date') ?? '');
    const minutes = Number(form.get('daily_minutes') ?? 90);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(examDate)) return fail(400, { error: 'Choose your exam date.' });
    if (!Number.isFinite(minutes) || minutes < 15 || minutes > 600) {
      return fail(400, { error: 'Daily study time must be between 15 and 600 minutes.' });
    }
    const timezone = String(form.get('timezone') ?? '') || null;
    const result = await saveProfile(event, { exam_date: examDate, daily_minutes: minutes, timezone });
    if (result.state !== 'ok') {
      return fail(503, { error: failureMessage(result, 'The study planner is not online yet; nothing was saved.') });
    }
    return { saved: true };
  },
  review: async (event) => {
    const form = await event.request.formData();
    const cardId = String(form.get('card_id') ?? '');
    const rating = String(form.get('rating') ?? '') as Rating;
    if (!cardId || !RATINGS.includes(rating)) return fail(400, { error: 'Invalid review.' });
    const result = await reviewCard(event, cardId, rating);
    if (result.state !== 'ok') {
      return fail(503, { error: failureMessage(result, 'Reviews are not online yet.') });
    }
    return { reviewed: cardId };
  }
};
