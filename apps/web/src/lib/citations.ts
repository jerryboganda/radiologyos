// Citation formatting and deep links into the reader. Pure for node --test.
import type { Citation, LooseCitation } from './types/citation';

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

export type CitationLink =
  | { kind: 'source'; href: string; label: string }
  | { kind: 'web'; href: string; label: string };

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

/** The first cited block as (page, block), from either block envelope. */
function firstBlock(c: LooseCitation, from: number): { page: number; block: number } | null {
  const refs = (Array.isArray(c.block_refs) ? c.block_refs : [])
    .map((r) => ({ page: num(r?.page), block: num(r?.block) }))
    .concat((Array.isArray(c.blocks) ? c.blocks : []).map((b) => ({ page: num(b?.page_no), block: num(b?.block_no) })))
    .filter((r): r is { page: number; block: number } => r.page !== null && r.block !== null);
  return refs.find((r) => r.page >= from) ?? refs[0] ?? null;
}

/**
 * Normalise any API citation (tutor, card, assessment, knowledge) into a link:
 * library citations open the reader at page/block; web citations are external.
 * Returns null for anything that cannot be resolved safely.
 */
export function citationLink(c: LooseCitation | null | undefined): CitationLink | null {
  if (!c || typeof c !== 'object') return null;
  if (c.kind === 'web' || (!c.source_id && typeof c.url === 'string')) {
    const href = typeof c.url === 'string' ? safeWebUrl(c.url) : null;
    return href ? { kind: 'web', href, label: `From the web · ${webHost(href)}` } : null;
  }
  if (typeof c.source_id !== 'string' || !isUuid(c.source_id)) return null;
  const from = num(c.page_from) ?? num(c.page_no) ?? 1;
  const to = num(c.page_to) ?? from;
  const title = typeof c.source_title === 'string' ? c.source_title : '';
  const block = firstBlock(c, from);
  const label = citationLabel({ source_title: title, page_from: from, page_to: to });
  const href = block ? readerHref(c.source_id, block.page, block.block) : readerHref(c.source_id, from);
  return { kind: 'source', href, label: c.kind === 'figure' ? `${label} · figure` : label };
}
