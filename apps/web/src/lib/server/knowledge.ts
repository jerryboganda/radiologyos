// Knowledge API client (planned: /v1/knowledge/*).
import type { RequestEvent } from '@sveltejs/kit';
import type { Concept, Conflict, TopicWeight } from '$lib/types/knowledge';
import { getJson, sendJson } from './client';

export const listConcepts = (event: RequestEvent) => getJson<Concept[]>(event, '/v1/knowledge/concepts');

export const listConflicts = (event: RequestEvent) => getJson<Conflict[]>(event, '/v1/knowledge/conflicts');

export const listTopicWeights = (event: RequestEvent) =>
  getJson<TopicWeight[]>(event, '/v1/knowledge/topic-weights');

/** Owner approval of a proposed curriculum weight (never automatic). */
export const approveTopicWeight = (event: RequestEvent, id: string) =>
  sendJson<TopicWeight>(event, `/v1/knowledge/topic-weights/${encodeURIComponent(id)}/approve`, 'POST');
