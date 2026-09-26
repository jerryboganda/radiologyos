// Citation formatting and deep links into the reader. Pure for node --test.
import type { Citation } from './types/citation';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

function positiveInt(value: number): number | null {
  return Number.isInteger(value) && value >= 1 ? value : null;
}

/** `/library/{source}?page=N&block=M` — the reader highlights block M on page N. */
export function readerHref(sourceId: string, page: number, block?: number | null): string {
  const params = new URLSearchParams();
  params.set('page', String(positiveInt(page) ?? 1));
  if (typeof block === 'number' && Number.isInteger(block) && block >= 0) {
    params.set('block', String(block));
  }
  return `/library/${encodeURIComponent(sourceId)}?${params.toString()}`;
}

export function pageRange(from: number, to: number): string {
  return to > from ? `p.${from}–${to}` : `p.${from}`;
}

/** "Source title · p.3–5" */
export function citationLabel(citation: Pick<Citation, 'source_title' | 'page_from' | 'page_to'>): string {
  const title = citation.source_title.trim() || 'Untitled source';
  return `${title} · ${pageRange(citation.page_from, citation.page_to)}`;
}

/** Deep link to the first cited block (falls back to the first cited page). */
export function citationHref(citation: Citation): string {
  const first = citation.block_refs.find((ref) => ref.page >= citation.page_from) ?? citation.block_refs[0];
  if (first) return readerHref(citation.source_id, first.page, first.block);
  return readerHref(citation.source_id, citation.page_from);
}

/** Only http(s) links may be rendered as web citations. */
export function safeWebUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function webHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
