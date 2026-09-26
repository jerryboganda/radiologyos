// Planned knowledge API (/v1/knowledge/*).
import type { Citation } from './citation';

export interface Concept {
  id: string;
  name: string;
  topic?: string | null;
  claim_count: number;
  source_count: number;
}

export interface ConflictClaim {
  text: string;
  citation: Citation;
}

export interface Conflict {
  id: string;
  concept: string;
  summary: string;
  status: string;
  claims: ConflictClaim[];
}

export interface TopicWeight {
  id: string;
  code: string;
  name: string;
  current: number | null;
  proposed: number;
  rationale?: string | null;
  status: 'proposed' | 'approved' | 'rejected' | string;
  citations?: Citation[];
}
