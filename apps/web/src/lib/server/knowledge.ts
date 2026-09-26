// Knowledge API client (apps/api/app/api/knowledge.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  ApproveRequest,
  ApproveResponse,
  ConceptDetail,
  ConceptSummary,
  ConflictOut,
  ExtractRequest,
  ExtractResponse,
  ResolveRequest,
  TopicWeightOut,
  WeightTarget
} from '$lib/types/knowledge';
import { getJson, query, sendJson } from './client';

const K = '/v1/knowledge';

export const listConcepts = (event: RequestEvent, q: string | null, limit = 60) =>
  getJson<ConceptSummary[]>(event, `${K}/concepts${query({ q, limit })}`);

export const getConcept = (event: RequestEvent, id: string) =>
  getJson<ConceptDetail>(event, `${K}/concepts/${encodeURIComponent(id)}`);

export const listConflicts = (event: RequestEvent, status: 'open' | 'resolved' = 'open') =>
  getJson<ConflictOut[]>(event, `${K}/conflicts${query({ status })}`);

export const resolveConflict = (event: RequestEvent, id: string, body: ResolveRequest) =>
  sendJson<ConflictOut>(event, `${K}/conflicts/${encodeURIComponent(id)}/resolve`, 'POST', body);

export const listTopicWeights = (event: RequestEvent, target: WeightTarget | null) =>
  getJson<TopicWeightOut[]>(event, `${K}/topic-weights${query({ exam_target: target })}`);

/** Owner approval of computed curriculum weights (never automatic). */
export const approveTopicWeights = (event: RequestEvent, body: ApproveRequest) =>
  sendJson<ApproveResponse>(event, `${K}/topic-weights/approve`, 'POST', body);

export const extractSource = (event: RequestEvent, sourceId: string, body: ExtractRequest) =>
  sendJson<ExtractResponse>(event, `${K}/sources/${encodeURIComponent(sourceId)}/extract`, 'POST', body);
