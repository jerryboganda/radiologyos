// Knowledge API client (apps/api/app/api/knowledge.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  ApproveRequest,
  ApproveResponse,
  ConceptDetail,
  ConceptSummary,
  ConflictOut,
  CurriculumSystem,
  ExtractRequest,
  ExtractResponse,
  MappingDecision,
  MappingOut,
  MappingStatus,
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

/** Curriculum mappings awaiting review (low classifier confidence). */
export const listMappings = (event: RequestEvent, status: MappingStatus = 'review') =>
  getJson<MappingOut[]>(event, `${K}/mappings${query({ status })}`);

/** Accept, reject, or re-code one mapping (audited by the API). */
export const decideMapping = (event: RequestEvent, id: string, body: MappingDecision) =>
  sendJson<MappingOut>(event, `${K}/mappings/${encodeURIComponent(id)}/decide`, 'POST', body);

export const listCurriculumSystems = (event: RequestEvent) =>
  getJson<CurriculumSystem[]>(event, `${K}/curriculum/systems`);

export const extractSource =(event: RequestEvent, sourceId: string, body: ExtractRequest) =>
  sendJson<ExtractResponse>(event, `${K}/sources/${encodeURIComponent(sourceId)}/extract`, 'POST', body);
