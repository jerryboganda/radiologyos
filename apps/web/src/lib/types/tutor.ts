// Tutor API contract (apps/api/app/api/tutor.py, packages/tutor/models.py).
// Every segment carries at least one verified citation; web segments carry URL
// citations and are always labelled "From the web" in the UI.
import type { BlockRef } from './citation';

export type Grounding = 'sources' | 'web' | 'mixed' | 'none';

export interface TutorCitation {
  kind: 'source' | 'web';
  label?: string | null;
  chunk_id?: string | null;
  source_id?: string | null;
  source_title?: string | null;
  page_from?: number | null;
  page_to?: number | null;
  block_refs?: BlockRef[];
  url?: string | null;
}

export interface Segment {
  text: string;
  origin: 'sources' | 'web';
  citations: TutorCitation[];
}

export interface AskRequest {
  question: string;
  thread_id?: string | null;
  allow_web?: boolean;
}

export interface AskResponse {
  thread_id: string;
  message_id: string;
  grounding: Grounding;
  segments: Segment[];
  notice: string | null;
  dropped_segments: number;
  agent_version: string;
  excerpts_considered: number;
}

export interface ThreadSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ThreadMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  grounding: Grounding | null;
  segments: Segment[];
  agent_version: string;
  created_at: string;
}

export interface ThreadDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ThreadMessage[];
}

export const GROUNDING_LABEL: Record<Grounding, string> = {
  sources: 'Grounded in your library',
  web: 'From the web',
  mixed: 'Your library + the web',
  none: 'No grounded answer'
};
