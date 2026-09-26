// Tutor API contract (apps/api/app/api/tutor.py, packages/tutor/models.py).
// Every segment carries at least one verified citation; web segments carry URL
// citations and are always labelled "From the web" in the UI. Figure citations
// resolve to a figure id + page and render as thumbnails via /media/figures/{id}.
// `support` is the semantic grounding judge's verdict (ADR 0013 v2). Attached
// images and their AI readings are context, never citations (ADR 0025).
import type { BlockRef } from './citation';

export type Grounding = 'sources' | 'web' | 'mixed' | 'none';

export type Support = 'supported' | 'partial' | 'not_verified';

export interface TutorCitation {
  kind: 'source' | 'web' | 'figure';
  label?: string | null;
  chunk_id?: string | null;
  figure_id?: string | null;
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
  support?: Support | null;
  support_note?: string | null;
}

export interface JudgeStats {
  status: 'ok' | 'failed' | 'skipped' | 'not_run';
  judged: number;
  supported: number;
  partial: number;
  unsupported: number;
  not_verified: number;
  web_unjudged: number;
  agent_version: string;
}

/** The Reader page a question is about (ADR 0025): its excerpts are retrieved first. */
export interface Focus {
  source_id: string;
  page_no: number;
}

/** AI reading of an image attached to a question: context only, never a citation. */
export interface ImageReading {
  modality: string;
  anatomy: string;
  visible_text: string;
  findings: string[];
  impression: string;
  differentials: string[];
  teaching_points: string[];
  topics: string[];
  confidence: 'low' | 'medium' | 'high';
}

export interface AskRequest {
  question: string;
  thread_id?: string | null;
  allow_web?: boolean;
  image_id?: string | null;
  focus?: Focus | null;
}

export interface ImageUpload {
  image_id: string;
  content_type: string;
  byte_size: number;
  width: number;
  height: number;
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
  figures_considered: number;
  judge: JudgeStats | null;
  image_id?: string | null;
  image_reading?: ImageReading | null;
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
  judge?: JudgeStats | null;
  image_id?: string | null;
  image_reading?: ImageReading | null;
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

export const SUPPORT_LABEL: Record<Support, string> = {
  supported: 'Checked against the cited text',
  partial: 'Partially supported',
  not_verified: 'Not verified'
};
