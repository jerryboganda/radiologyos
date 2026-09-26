// Citation shapes returned by the API. Library citations resolve to
// source/page/block; every area uses a slightly different envelope, so the UI
// normalises them through `citationLink` (src/lib/citations.ts).
export interface BlockRef {
  page: number;
  block: number;
}

/** Library search citation (apps/api/app/api/library.py Citation). */
export interface Citation {
  source_id: string;
  source_title: string;
  page_from: number;
  page_to: number;
  block_refs: BlockRef[];
}

/** A block located by knowledge extraction (packages/knowledge/evidence.py). */
export interface LocatedBlock {
  page_no: number;
  block_no: number;
  bbox?: number[];
}

/**
 * Any citation the API emits: tutor (`kind` source|web), study card, assessment
 * (`kind` chunk|figure), or knowledge claim (`blocks`). All fields optional so
 * one normaliser handles them defensively.
 */
export interface LooseCitation {
  kind?: string | null;
  label?: string | null;
  url?: string | null;
  chunk_id?: string | null;
  figure_id?: string | null;
  source_id?: string | null;
  source_title?: string | null;
  page_from?: number | null;
  page_to?: number | null;
  page_no?: number | null;
  block_refs?: BlockRef[] | null;
  blocks?: LocatedBlock[] | null;
}
