// Library API contract (apps/api/app/api/library.py, docs/openapi.json).
import type { Citation } from './citation';

export type SourceKind = 'pdf' | 'docx' | 'pptx' | 'image' | string;

export interface SourceSummary {
  id: string;
  title: string;
  kind: SourceKind;
  status: string;
  page_count: number | null;
  byte_size: number | null;
  created_at: string;
  pages_parsed: number;
  figure_count: number;
}

export interface StepStatus {
  step: string;
  status: string;
  attempts: number;
  error_code: string | null;
  output_ref: string | null;
}

export interface SourceDetail {
  id: string;
  title: string;
  kind: SourceKind;
  status: string;
  page_count: number | null;
  byte_size: number | null;
  created_at: string;
  steps: StepStatus[];
}

export interface PageBlock {
  block_no: number;
  kind: string;
  text: string;
  bbox: number[];
  origin: string;
}

export interface PageFigure {
  id: string;
  figure_no: number;
  bbox: number[];
  caption: string;
  description: string;
  modality: string;
  anatomy: string;
  findings: string[] | null;
  image_path: string | null;
}

export interface ReaderPage {
  source_id: string;
  title: string;
  page_no: number;
  page_count: number | null;
  width: number | null;
  height: number | null;
  text_origin: string | null;
  vision_status: string | null;
  image_path: string | null;
  blocks: PageBlock[];
  figures: PageFigure[];
  /** Structured table blocks of this page (ADR 0030). */
  tables?: PageTable[];
}

export interface PageTable {
  id: string;
  block_no: number;
  bbox: number[];
  n_rows: number;
  n_cols: number;
  header: boolean;
  cells: string[][];
}

export interface TableHit extends Omit<PageTable, 'id'> {
  table_id: string;
  source_id: string;
  source_title: string;
  page_no: number;
  score: number;
}

export interface ReprocessResponse {
  source_id: string;
  job_id: string;
  retried_pages: number;
}

export interface UploadResponse {
  source_id: string;
  job_id: string | null;
  duplicate: boolean;
}

export interface SearchHit {
  chunk_id: string;
  heading: string;
  text: string;
  score: number;
  citation: Citation;
}

export interface FigureHit {
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

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  figures: FigureHit[];
  dense: boolean;
  tables?: TableHit[];
}

/** A source row in the library list, with steps when it is still processing. */
export interface SourceRow extends SourceSummary {
  steps: StepStatus[] | null;
}
