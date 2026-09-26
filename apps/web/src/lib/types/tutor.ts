// Planned tutor API (/v1/tutor/*). Every segment carries citations; web-sourced
// segments carry URLs and are always labelled "From the web" in the UI.
import type { Citation, WebCitation } from './citation';

export type SegmentOrigin = 'library' | 'web' | 'ungrounded';

export interface TutorSegment {
  text: string;
  origin: SegmentOrigin;
  citations: Citation[];
  web_sources: WebCitation[];
}

export interface TutorAnswer {
  thread_id: string;
  question: string;
  segments: TutorSegment[];
  grounding: string;
  message?: string | null;
}

export interface TutorThread {
  id: string;
  title: string;
  updated_at: string;
}

export interface TutorThreadDetail extends TutorThread {
  turns: TutorAnswer[];
}
