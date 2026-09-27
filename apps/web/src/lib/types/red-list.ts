// The owner's red review list (apps/api/app/api/red_list.py, ADR 0038).

export type RedItemKind = 'page' | 'figure' | 'notes';

export interface RedItem {
  id: string;
  source_id: string;
  source_title: string;
  kind: RedItemKind;
  page_from: number | null;
  page_to: number | null;
  reason: string;
  created_at: string;
}

export interface FlaggedFact {
  id: string;
  statement: string;
  doubt: string | null;
  evidence_span: string;
  source_id: string;
  source_title: string;
  page_from: number;
  page_to: number;
}

export interface RedList {
  items: RedItem[];
  flagged_facts: FlaggedFact[];
}

export type FactDecision = 'keep' | 'reject';
