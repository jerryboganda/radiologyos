// Shared citation shapes. Library citations resolve to source/page/block.
export interface BlockRef {
  page: number;
  block: number;
}

export interface Citation {
  source_id: string;
  source_title: string;
  page_from: number;
  page_to: number;
  block_refs: BlockRef[];
}

/** A web-sourced reference (tutor answers may include these, always labelled). */
export interface WebCitation {
  url: string;
  title?: string | null;
}
