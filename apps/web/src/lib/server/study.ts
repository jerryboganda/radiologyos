// Study API client (planned: /v1/study/*).
import type { RequestEvent } from '@sveltejs/kit';
import type { DueCards, Rating, StudyProfile, StudyProgress, TodayPlan } from '$lib/types/study';
import { getJson, sendJson } from './client';

export const getProfile = (event: RequestEvent) => getJson<StudyProfile>(event, '/v1/study/profile');

export const saveProfile = (event: RequestEvent, profile: StudyProfile) =>
  sendJson<StudyProfile>(event, '/v1/study/profile', 'PUT', profile);

export const getToday = (event: RequestEvent) => getJson<TodayPlan>(event, '/v1/study/today');

export const getDueCards = (event: RequestEvent, limit = 20) =>
  getJson<DueCards>(event, `/v1/study/cards/due?limit=${limit}`);

export const reviewCard = (event: RequestEvent, cardId: string, rating: Rating) =>
  sendJson<unknown>(event, `/v1/study/cards/${encodeURIComponent(cardId)}/review`, 'POST', { rating });

export const getProgress = (event: RequestEvent) => getJson<StudyProgress>(event, '/v1/study/progress');
