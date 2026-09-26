// Study API client (apps/api/app/api/study.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  CardOut,
  GenerateCardsIn,
  GenerateCardsOut,
  PlanOut,
  ProfileIn,
  ProfileOut,
  ProgressOut,
  Rating,
  ReviewOut
} from '$lib/types/study';
import { getJson, sendJson } from './client';

/** 404 until onboarding has saved an exam date. */
export const getProfile = (event: RequestEvent) => getJson<ProfileOut>(event, '/v1/study/profile');

export const saveProfile = (event: RequestEvent, profile: ProfileIn) =>
  sendJson<ProfileOut>(event, '/v1/study/profile', 'PUT', profile);

/** 409 until a profile exists (onboarding). */
export const getToday = (event: RequestEvent, refresh = false) =>
  getJson<PlanOut>(event, `/v1/study/today${refresh ? '?refresh=true' : ''}`);

export const getDueCards = (event: RequestEvent, limit = 50) =>
  getJson<CardOut[]>(event, `/v1/study/cards/due?limit=${limit}`);

export const reviewCard = (event: RequestEvent, cardId: string, rating: Rating) =>
  sendJson<ReviewOut>(event, `/v1/study/cards/${encodeURIComponent(cardId)}/review`, 'POST', { rating });

/** Model-backed (503 not configured / usage limit, 502 retry). */
export const generateCards = (event: RequestEvent, body: GenerateCardsIn) =>
  sendJson<GenerateCardsOut>(event, '/v1/study/cards/generate', 'POST', body, { timeoutMs: 300_000 });

/** 409 until a profile exists. */
export const getProgress = (event: RequestEvent) => getJson<ProgressOut>(event, '/v1/study/progress');
