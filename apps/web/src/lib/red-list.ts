// The owner's red review list (ADR 0038): plain-English reasons, labels, shape
// guard, and form parsing. Pure for node --test.
import type { FactDecision, FlaggedFact, RedItem, RedItemKind, RedList } from './types/red-list.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KINDS: readonly string[] = ['page', 'figure', 'notes'];

const REASONS: Record<string, string> = {
  low_text_coverage: "The reading missed part of this page's own text",
  empty_reading_of_text_page: 'No text could be read from a page that has text',
  bbox_out_of_range: 'The page layout could not be mapped',
  empty_reading: 'Nothing could be read from this image',
  unverified_source_quote: 'The diagnosis could not be matched to your slide',
  unsupported_claims: 'Many statements lacked supporting evidence on the page',
  all_models_failed: 'Every AI model failed on this item',
  no_usable_answer: 'No model gave a usable answer',
  claude_quota: 'Waiting for Claude quota to finish the check',
  'soft:low_confidence': 'Low-confidence diagnosis',
  'soft:source_doubt': 'Your source may contradict standard teaching',
  'soft:context_free_claims': 'Statements lacked context'
};
const FALLBACK_REASON = 'Fell short of the quality check';

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

/** A radiologist-facing sentence for a gate reason code. */
export function reasonText(code: string): string {
  return Object.hasOwn(REASONS, code) ? REASONS[code] : FALLBACK_REASON;
}

export function kindLabel(kind: RedItemKind): string {
  return kind === 'page' ? 'Page' : kind === 'figure' ? 'Figure' : 'Notes';
}

/** "page 12", "pages 14–15", or '' when the location is unknown. */
export function pagesLabel(from: number | null, to: number | null): string {
  const start = from ?? to;
  if (start === null) return '';
  const end = to ?? start;
  return end > start ? `pages ${start}–${end}` : `page ${start}`;
}

/** The reader page an item points at (its first page; page 1 when unknown). */
export function itemPage(from: number | null, to: number | null): number {
  const page = from ?? to;
  return page !== null && Number.isInteger(page) && page > 0 ? page : 1;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPage(value: unknown, nullable: boolean): boolean {
  return (nullable && value === null) || (typeof value === 'number' && Number.isInteger(value));
}

function isItem(value: unknown): value is RedItem {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.source_id === 'string' &&
    typeof value.source_title === 'string' &&
    typeof value.kind === 'string' &&
    KINDS.includes(value.kind) &&
    isPage(value.page_from, true) &&
    isPage(value.page_to, true) &&
    typeof value.reason === 'string' &&
    typeof value.created_at === 'string'
  );
}

function isFact(value: unknown): value is FlaggedFact {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.statement === 'string' &&
    (value.doubt === null || typeof value.doubt === 'string') &&
    typeof value.evidence_span === 'string' &&
    typeof value.source_id === 'string' &&
    typeof value.source_title === 'string' &&
    isPage(value.page_from, false) &&
    isPage(value.page_to, false)
  );
}

/** Validates the GET /v1/library/red-list response shape. */
export function isRedList(value: unknown): value is RedList {
  if (!isRecord(value)) return false;
  const { items, flagged_facts } = value;
  return Array.isArray(items) && items.every(isItem) && Array.isArray(flagged_facts) && flagged_facts.every(isFact);
}

/** Everything still waiting for the owner. */
export function redCount(list: RedList | null): number {
  return list ? list.items.length + list.flagged_facts.length : 0;
}

export function parseReviewedForm(form: FormData): Parsed<{ id: string }> {
  const id = String(form.get('id') ?? '');
  return UUID.test(id) ? { ok: true, value: { id } } : { ok: false, error: 'Unknown item.' };
}

export function parseFactForm(form: FormData): Parsed<{ id: string; decision: FactDecision }> {
  const id = String(form.get('id') ?? '');
  if (!UUID.test(id)) return { ok: false, error: 'Unknown fact.' };
  const decision = form.get('decision');
  if (decision !== 'keep' && decision !== 'reject') return { ok: false, error: 'Choose keep or reject.' };
  return { ok: true, value: { id, decision } };
}
