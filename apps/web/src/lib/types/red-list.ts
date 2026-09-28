// The owner's red review list (apps/api/app/api/red_list.py, ADR 0038, ADR 0041).

export type RedItemKind = 'page' | 'figure' | 'notes';
export type RedStatus = 'open' | 'reviewed';
export type Verdict = 'correct' | 'needs_fix' | 'remove';
export type FactDecision = 'keep' | 'reject';

export interface Statement {
  statement: string;
  evidence_span: string;
  status: string;
}

export interface FigureDetail {
  id: string;
  figure_no: number | null;
  caption: string | null;
  description: string | null;
  modality: string | null;
  anatomy: string | null;
  findings: string[];
  source_quote: string | null;
  impression_origin: string | null;
  has_image: boolean;
}

export interface RedItem {
  id: string;
  source_id: string;
  source_title: string;
  file_name: string;
  kind: RedItemKind;
  page_from: number | null;
  page_to: number | null;
  reason: string;
  status: 'review' | 'reviewed';
  verdict: Verdict | null;
  note: string | null;
  created_at: string;
  page_status: string | null;
  own_text: string | null;
  reading: string | null;
  figures: FigureDetail[];
  section_heading: string | null;
  section_text: string | null;
  statements: Statement[];
}

export interface FlaggedFact {
  id: string;
  statement: string;
  doubt: string | null;
  evidence_span: string;
  source_id: string;
  source_title: string;
  file_name: string;
  page_from: number;
  page_to: number;
  /** flagged (open), active (kept) or rejected. */
  status: string;
  note: string | null;
  decided_at: string | null;
  section_heading: string | null;
  section_text: string | null;
}

export interface RedList {
  items: RedItem[];
  flagged_facts: FlaggedFact[];
}

/** GET /v1/library/red-list/summary: one row per file. */
export interface FileSummary {
  source_id: string;
  source_title: string;
  file_name: string;
  open_pages: number;
  open_figures: number;
  open_notes: number;
  open_facts: number;
  reviewed: number;
  reasons: Record<string, number>;
}
