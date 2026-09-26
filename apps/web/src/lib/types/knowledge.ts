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
  /** Conflict agent verdict (ADR 0030); null until the depth pass has run. */
  ai_label?: 'conflict' | 'context' | 'same' | null;
  ai_confidence?: number | null;
  ai_rationale?: string | null;
  ai_context?: string | null;
  ai_cites?: string[] | null;
  /** The owner's "trust source" decision, when that is how it was resolved. */
  trust?: TrustChoice | null;
}

export type TrustChoice = 'a' | 'b' | 'both';

export interface TrustRequest {
  trust: TrustChoice;
  note?: string;
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
  /** Curriculum title when the topic is a coded tree node (ADR 0023). */
  topic_title?: string | null;
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
  /** Most specific curriculum node (system, topic, or subtopic); null = system level. */
  curriculum_node_id?: string | null;
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
  /** A curriculum node id at any depth when re-coding. */
  curriculum_code?: string | null;
}

export interface CurriculumSystem {
  code: string;
  title: string;
}

// Curriculum tree and owner approval (apps/api/app/api/curriculum.py, ADR 0023).
export type CurriculumLevel = 'system' | 'topic' | 'subtopic';
export type CurriculumFilter = 'fcps2_theory' | 'fcps2_toacs' | 'imm' | 'frcr' | 'frcr_2a' | 'frcr_2b';
export const CURRICULUM_FILTERS: { value: CurriculumFilter; label: string }[] = [
  { value: 'fcps2_theory', label: 'FCPS-II theory' },
  { value: 'fcps2_toacs', label: 'FCPS-II TOACS' },
  { value: 'imm', label: 'IMM' },
  { value: 'frcr_2a', label: 'FRCR 2A' },
  { value: 'frcr_2b', label: 'FRCR 2B' }
];

export interface CurriculumTreeNode {
  code: string;
  title: string;
  level: CurriculumLevel;
  exams: string[];
  children: CurriculumTreeNode[];
}

export type CurriculumReviewStatus = 'pending' | 'approved' | 'rejected';

export interface CurriculumStatus {
  pack_id: string;
  version: string;
  pack_status: string;
  content_hash: string;
  source: string;
  sources: string[];
  counts: Record<string, number>;
  review_status: CurriculumReviewStatus;
  decided_at: string | null;
  notes: string;
}

export interface CurriculumOut extends CurriculumStatus {
  systems: CurriculumTreeNode[];
}

export interface CurriculumDecision {
  decision: 'approved' | 'rejected';
  content_hash: string;
  notes?: string;
}

export interface NodeCandidate {
  id: string;
  path: string;
  label: string;
  level: CurriculumLevel;
}

// Knowledge depth (apps/api/app/api/knowledge_depth.py, ADR 0030).
export interface NoteSentence {
  text: string;
  claim_ids: string[];
}

export interface NoteBody {
  definition: NoteSentence[];
  imaging: { modality: string; sentences: NoteSentence[] }[];
  differentials: { name: string; concept_id: string | null; discriminators: NoteSentence[] }[];
  pearls: NoteSentence[];
  pitfalls: NoteSentence[];
}

export interface ConceptNoteOut {
  id: string;
  version: number;
  status: 'draft' | 'verified' | 'superseded';
  body: NoteBody;
  sentences: number;
  dropped: number;
  agent_version: string;
  verified_at: string | null;
  created_at: string;
}

export interface NoteState {
  concept_id: string;
  state: 'missing' | 'current' | 'stale';
  open_conflicts: number;
  verifiable: boolean;
  note: ConceptNoteOut | null;
}

export interface GraphOut {
  center: string;
  depth: number;
  nodes: { id: string; name: string; concept_type: string; depth: number }[];
  edges: { source: string; target: string; relation: string }[];
}

export interface RelatedFigure {
  figure_id: string;
  source_id: string;
  source_title: string;
  page_no: number;
  caption: string;
  description: string;
  modality: string;
  anatomy: string;
  image_path: string | null;
}

export type MergeStatus = 'review' | 'applied' | 'distinct' | 'undone';

export interface MergeOut {
  id: string;
  concept_a: string;
  a_name: string;
  concept_b: string;
  b_name: string;
  similarity: number;
  decision: string;
  confidence: number;
  rationale: string;
  status: MergeStatus;
  survivor: string | null;
  merged: string | null;
  moved_claims: number;
  agent_version: string;
  created_at: string;
  applied_at: string | null;
  undone_at: string | null;
}
