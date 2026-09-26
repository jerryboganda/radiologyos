// Knowledge API contract (apps/api/app/api/knowledge.py).
import type { LooseCitation } from './citation';

export type WeightTarget = 'imm' | 'fcps2_theory' | 'fcps2_toacs' | 'frcr' | 'unknown' | 'all';
export const WEIGHT_TARGETS: WeightTarget[] = ['fcps2_theory', 'fcps2_toacs', 'imm', 'frcr', 'unknown', 'all'];

export interface ConceptSummary {
  id: string;
  name: string;
  aliases: string[];
  concept_type: string;
  curriculum_code: string | null;
  claim_count: number;
  open_conflicts: number;
}

export interface ClaimOut {
  id: string;
  claim_type: string;
  statement: string;
  evidence_span: string;
  status: string;
  verification: string;
  importance: number;
  modality: string;
  citation: LooseCitation;
  supporting: LooseCitation[];
  agent_version: string;
}

export interface EdgeOut {
  id: string;
  relation: string;
  direction: 'in' | 'out';
  other_id: string;
  other_name: string;
  citation: LooseCitation;
}

export interface ConflictSide {
  claim_id: string;
  statement: string;
  evidence_span: string;
  citation: LooseCitation;
}

export interface ConflictOut {
  id: string;
  concept_id: string;
  concept_name: string;
  kind: string;
  description: string;
  status: 'open' | 'resolved' | string;
  resolution: string | null;
  preferred_claim: string | null;
  resolved_at: string | null;
  created_at: string;
  claim_a: ConflictSide;
  claim_b: ConflictSide;
}

export interface ConceptDetail {
  id: string;
  name: string;
  aliases: string[];
  concept_type: string;
  curriculum_code: string | null;
  curriculum_confidence: number | null;
  summary: string;
  claims: ClaimOut[];
  edges: EdgeOut[];
  conflicts: ConflictOut[];
}

export interface ResolveRequest {
  resolution: string;
  preferred_claim_id?: string | null;
}

/** How a past-paper weight was derived (packages/knowledge/weights.py). */
export interface WeightBasis {
  method?: string;
  alpha?: number;
  count?: number;
  total?: number;
  categories?: number;
  papers?: number;
  total_papers?: number;
  years?: number[];
}

export interface TopicWeightOut {
  id: string;
  exam_target: string;
  curriculum_code: string;
  topic: string;
  weight: number;
  basis: WeightBasis;
  approved: boolean;
  approved_at: string | null;
  computed_at: string;
}

export interface ApproveRequest {
  exam_target: WeightTarget;
  weight_ids?: string[] | null;
}

export interface ApproveResponse {
  exam_target: string;
  approved: number;
}

export interface ExtractRequest {
  mode: 'notes' | 'past_paper';
  exam_target?: Exclude<WeightTarget, 'all'> | null;
  year?: number | null;
}

export interface ExtractResponse {
  source_id: string;
  job_id: string;
  mode: string;
}

export type MappingStatus = 'accepted' | 'review' | 'rejected';

/** A classifier's curriculum mapping for one unit of a source (GET /v1/knowledge/mappings). */
export interface MappingOut {
  id: string;
  source_id: string;
  source_title: string;
  page_from: number;
  page_to: number;
  curriculum_code: string;
  topic: string;
  confidence: number;
  status: MappingStatus;
  agent_version: string;
  created_at: string;
  /** Start of the mapped chunk (the owner's own text), for context. */
  excerpt: string;
}

export type MappingDecisionKind = 'accept' | 'reject' | 'code';

export interface MappingDecision {
  decision: MappingDecisionKind;
  curriculum_code?: string | null;
}

export interface CurriculumSystem {
  code: string;
  title: string;
}
