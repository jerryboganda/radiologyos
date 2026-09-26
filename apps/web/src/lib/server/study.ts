// Study API client (apps/api/app/api/study.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  BaselineOut,
  CardOut,
  GenerateCardsIn,
  GenerateCardsOut,
  KnowledgeCardsIn,
  KnowledgeCardsOut,
  PlanOut,
  ProfileIn,
  ProfileOut,
  ProgressOut,
  Rating,
  ReviewOut,
  WeeklyReportOut
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

/** No model call: cloze cards from verified claims or image cards from figures (ADR 0029). */
export const cardsFromKnowledge = (event: RequestEvent, body: KnowledgeCardsIn) =>
  sendJson<KnowledgeCardsOut>(event, '/v1/study/cards/from-knowledge', 'POST', body);

/** 409 until a profile exists. */
export const getProgress = (event: RequestEvent) => getJson<ProgressOut>(event, '/v1/study/progress');

/** 404 until a baseline exists. Reading it freezes results once its exam is submitted. */
export const getBaseline = (event: RequestEvent) => getJson<BaselineOut>(event, '/v1/study/baseline');

/** Returns the open baseline or builds one; 409 when too few checked SBA questions exist. */
export const startBaseline = (event: RequestEvent) =>
  sendJson<BaselineOut>(event, '/v1/study/baseline', 'POST');

/** 404 until the first Monday-morning report has been written. */
export const getLatestReport = (event: RequestEvent) =>
  getJson<WeeklyReportOut>(event, '/v1/study/reports/latest');
