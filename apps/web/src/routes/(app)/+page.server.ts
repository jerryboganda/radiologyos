import { fail } from '@sveltejs/kit';
import { dataOr, loadProblem } from '$lib/api-state';
import { isUuid } from '$lib/citations';
import { failureMessage, getJson } from '$lib/server/client';
import { generateCards, getDueCards, getProfile, getToday, reviewCard, saveProfile } from '$lib/server/study';
import { needsOnboarding, parseProfileForm } from '$lib/study';
import { parseRating } from '$lib/types/study';
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
    getDueCards(event, 50),
    getJson<SourceSummary[]>(event, '/v1/library/sources')
  ]);
  const onboarding = needsOnboarding(profile, today);
  return {
    signedIn: true as const,
    authError: null,
    onboarding,
    profile: dataOr(profile, null),
    today: dataOr(today, null),
    todayProblem: onboarding ? null : loadProblem(today),
    due: dataOr(due, null),
    dueProblem: onboarding ? null : loadProblem(due),
    sources: dataOr(sources, [])
      .filter((s) => s.status === 'ready')
      .map((s) => ({ id: s.id, title: s.title })),
    sourceCount: sources.state === 'ok' ? sources.data.length : null
  };
};

export const actions: Actions = {
  onboard: async (event) => {
    const parsed = parseProfileForm(await event.request.formData());
    if (!parsed.ok) return fail(400, { section: 'onboard', error: parsed.error });
    const result = await saveProfile(event, parsed.profile);
    if (result.state !== 'ok') return fail(400, { section: 'onboard', error: failureMessage(result) });
    return { section: 'onboard', saved: true };
  },
  review: async (event) => {
    const form = await event.request.formData();
    const cardId = String(form.get('card_id') ?? '');
    const rating = parseRating(form.get('rating'));
    if (!isUuid(cardId) || rating === null) return fail(400, { section: 'review', error: 'Invalid review.' });
    const result = await reviewCard(event, cardId, rating);
    if (result.state !== 'ok') return fail(400, { section: 'review', error: failureMessage(result) });
    return { section: 'review', scheduledDays: result.data.scheduled_days };
  },
  generate: async (event) => {
    const form = await event.request.formData();
    const sourceId = String(form.get('source_id') ?? '');
    const maxCards = Number(form.get('max_cards') ?? 8);
    if (!isUuid(sourceId)) return fail(400, { section: 'generate', error: 'Choose a source.' });
    if (!Number.isInteger(maxCards) || maxCards < 1 || maxCards > 20) {
      return fail(400, { section: 'generate', error: 'Choose between 1 and 20 cards.' });
    }
    const result = await generateCards(event, { source_id: sourceId, max_cards: maxCards });
    if (result.state !== 'ok') return fail(400, { section: 'generate', error: failureMessage(result) });
    const { created, rejected, chunks_used } = result.data;
    return { section: 'generate', created: created.length, rejected, chunksUsed: chunks_used };
  }
};
