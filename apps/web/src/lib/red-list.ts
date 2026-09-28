// The owner's red review list (ADR 0038, ADR 0041): plain-English reasons and
// hints, labels, evidence highlighting, shape guards, and form parsing. Pure for
// node --test.
import type {
  FactDecision,
  FileSummary,
  FlaggedFact,
  RedItem,
  RedItemKind,
  RedList,
  Verdict
} from './types/red-list.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KINDS: readonly string[] = ['page', 'figure', 'notes'];
const VERDICTS: readonly string[] = ['correct', 'needs_fix', 'remove'];
export const NOTE_MAX = 4000;

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

const HINTS: Record<string, string> = {
  low_text_coverage: "Compare the page's own text with what the AI read; is anything important missing?",
  empty_reading_of_text_page: "The AI read nothing from this page; check the page's own text yourself.",
  bbox_out_of_range: 'The figure outlines may be misplaced; check the figures on this page.',
  empty_reading: 'Look at the image: is there a finding the AI missed?',
  unverified_source_quote: "Is the AI's diagnosis actually what the slide says?",
  unsupported_claims: 'Check each highlighted statement against the section text.',
  all_models_failed: 'No AI could read this; check the page yourself.',
  no_usable_answer: 'No AI gave a usable answer; check the page yourself.',
  claude_quota: 'The check is unfinished; look over the evidence yourself.',
  'soft:low_confidence': "Is the AI's diagnosis of this figure right?",
  'soft:source_doubt': 'Does your source contradict standard teaching here?',
  'soft:context_free_claims': 'Does each statement still make sense on its own?'
};
const FALLBACK_HINT = 'Compare the evidence below with the original page.';

const VERDICT_TEXT: Record<Verdict, string> = {
  correct: 'Correct as it is',
  needs_fix: 'Needs fixing',
  remove: 'Remove it'
};

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };
export interface Segment {
  text: string;
  mark: boolean;
}

/** A radiologist-facing sentence for a gate reason code. */
export function reasonText(code: string): string {
  return Object.hasOwn(REASONS, code) ? REASONS[code] : FALLBACK_REASON;
}

/** One line telling the owner what to look at for a reason code. */
export function reasonHint(code: string): string {
  return Object.hasOwn(HINTS, code) ? HINTS[code] : FALLBACK_HINT;
}

export function verdictText(verdict: Verdict): string {
  return VERDICT_TEXT[verdict];
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

/** Items in page order (unknown pages last); stable within a page. */
export function sortByPage(items: RedItem[]): RedItem[] {
  const key = (i: RedItem) => i.page_from ?? i.page_to ?? Number.MAX_SAFE_INTEGER;
  return [...items].sort((a, b) => key(a) - key(b));
}

/** Everything still open for one file. */
export function openCount(file: FileSummary): number {
  return file.open_pages + file.open_figures + file.open_notes + file.open_facts;
}

/** Open entries across every file (the Library page's pill). */
export function summaryCount(files: FileSummary[]): number {
  return files.reduce((sum, file) => sum + openCount(file), 0);
}

/** "12 pages · 3 figures · 40 note sections · 7 facts" (only non-zero parts). */
export function countsLabel(file: FileSummary): string {
  const parts: [number, string, string][] = [
    [file.open_pages, 'page', 'pages'],
    [file.open_figures, 'figure', 'figures'],
    [file.open_notes, 'note section', 'note sections'],
    [file.open_facts, 'fact', 'facts']
  ];
  return parts
    .filter(([n]) => n > 0)
    .map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
    .join(' · ');
}

/** Reason codes by count, largest first. */
export function topReasons(reasons: Record<string, number>, max = 4): [string, number][] {
  return Object.entries(reasons)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, max);
}

/** Everything still waiting for the owner in one list response. */
export function redCount(list: RedList | null): number {
  return list ? list.items.length + list.flagged_facts.length : 0;
}

// ---- highlighting -----------------------------------------------------------

interface Folded {
  text: string;
  /** Original index of each folded character. */
  at: number[];
}

/** Lower-case and collapse whitespace runs, remembering original positions. */
function fold(source: string): Folded {
  let text = '';
  const at: number[] = [];
  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (/\s/.test(ch)) {
      if (text.endsWith(' ')) continue;
      text += ' ';
    } else {
      const lower = ch.toLowerCase();
      text += lower.length === 1 ? lower : ch;
    }
    at.push(i);
  }
  return { text, at };
}

function ranges(text: string, spans: string[]): [number, number][] {
  const folded = fold(text);
  const found: [number, number][] = [];
  for (const span of spans) {
    const needle = typeof span === 'string' ? fold(span.trim()).text : '';
    if (needle.length < 3) continue;
    let from = folded.text.indexOf(needle);
    while (from !== -1) {
      const end = from + needle.length;
      found.push([folded.at[from], folded.at[end - 1] + 1]);
      from = folded.text.indexOf(needle, end);
    }
  }
  return merge(found);
}

function merge(found: [number, number][]): [number, number][] {
  const sorted = [...found].sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}

/**
 * Split `text` into plain and marked slices wherever one of `spans` occurs
 * (case-insensitive, whitespace-tolerant). Slices are always taken from the
 * original text; overlapping matches merge; spans under 3 characters are ignored.
 */
export function highlight(text: string, spans: string[]): Segment[] {
  if (typeof text !== 'string' || text === '') return [];
  const list = Array.isArray(spans) ? spans : [];
  const out: Segment[] = [];
  let cursor = 0;
  for (const [start, end] of ranges(text, list)) {
    if (start > cursor) out.push({ text: text.slice(cursor, start), mark: false });
    out.push({ text: text.slice(start, end), mark: true });
    cursor = end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), mark: false });
  return out;
}

// ---- shape guards -----------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPage(value: unknown, nullable: boolean): boolean {
  return (nullable && value === null) || (typeof value === 'number' && Number.isInteger(value));
}

function isText(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function isCount(value: unknown): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isFigure(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    Array.isArray(value.findings) &&
    ['caption', 'description', 'modality', 'anatomy', 'source_quote'].every((k) => isText(value[k])) &&
    typeof value.has_image === 'boolean'
  );
}

function isStatement(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return typeof value.statement === 'string' && typeof value.evidence_span === 'string' && typeof value.status === 'string';
}

function isEvidence(value: Record<string, unknown>): boolean {
  return (
    ['own_text', 'reading', 'section_heading', 'section_text', 'note'].every((k) => isText(value[k])) &&
    Array.isArray(value.figures) &&
    value.figures.every(isFigure) &&
    Array.isArray(value.statements) &&
    value.statements.every(isStatement)
  );
}

function isItem(value: unknown): value is RedItem {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.source_id === 'string' &&
    typeof value.source_title === 'string' &&
    typeof value.file_name === 'string' &&
    typeof value.kind === 'string' &&
    KINDS.includes(value.kind) &&
    isPage(value.page_from, true) &&
    isPage(value.page_to, true) &&
    typeof value.reason === 'string' &&
    (value.status === 'review' || value.status === 'reviewed') &&
    (value.verdict === null || (typeof value.verdict === 'string' && VERDICTS.includes(value.verdict))) &&
    typeof value.created_at === 'string' &&
    isEvidence(value)
  );
}

function isFact(value: unknown): value is FlaggedFact {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string' &&
    typeof value.statement === 'string' &&
    isText(value.doubt) &&
    typeof value.evidence_span === 'string' &&
    typeof value.source_id === 'string' &&
    typeof value.source_title === 'string' &&
    typeof value.file_name === 'string' &&
    isPage(value.page_from, false) &&
    isPage(value.page_to, false) &&
    typeof value.status === 'string' &&
    ['note', 'decided_at', 'section_heading', 'section_text'].every((k) => isText(value[k]))
  );
}

/** Validates the GET /v1/library/red-list response shape. */
export function isRedList(value: unknown): value is RedList {
  if (!isRecord(value)) return false;
  const { items, flagged_facts } = value;
  return Array.isArray(items) && items.every(isItem) && Array.isArray(flagged_facts) && flagged_facts.every(isFact);
}

function isFileSummary(value: unknown): value is FileSummary {
  if (!isRecord(value)) return false;
  const counts = ['open_pages', 'open_figures', 'open_notes', 'open_facts', 'reviewed'];
  return (
    typeof value.source_id === 'string' &&
    typeof value.source_title === 'string' &&
    typeof value.file_name === 'string' &&
    counts.every((k) => isCount(value[k])) &&
    isRecord(value.reasons) &&
    Object.values(value.reasons).every(isCount)
  );
}

/** Validates the GET /v1/library/red-list/summary response shape. */
export function isSummary(value: unknown): value is FileSummary[] {
  return Array.isArray(value) && value.every(isFileSummary);
}

// ---- form parsing -----------------------------------------------------------

function parseNote(form: FormData): Parsed<string> {
  const note = String(form.get('note') ?? '').trim();
  if (note.length > NOTE_MAX) return { ok: false, error: `Keep your note under ${NOTE_MAX} characters.` };
  return { ok: true, value: note };
}

export function parseVerdictForm(form: FormData): Parsed<{ id: string; verdict: Verdict; note: string }> {
  const id = String(form.get('id') ?? '');
  if (!UUID.test(id)) return { ok: false, error: 'Unknown item.' };
  const verdict = form.get('verdict');
  if (typeof verdict !== 'string' || !VERDICTS.includes(verdict)) {
    return { ok: false, error: 'Choose correct, needs fixing, or remove.' };
  }
  const note = parseNote(form);
  if (!note.ok) return note;
  return { ok: true, value: { id, verdict: verdict as Verdict, note: note.value } };
}

export function parseFactForm(form: FormData): Parsed<{ id: string; decision: FactDecision; note: string }> {
  const id = String(form.get('id') ?? '');
  if (!UUID.test(id)) return { ok: false, error: 'Unknown fact.' };
  const decision = form.get('decision');
  if (decision !== 'keep' && decision !== 'reject') return { ok: false, error: 'Choose keep or reject.' };
  const note = parseNote(form);
  if (!note.ok) return note;
  return { ok: true, value: { id, decision, note: note.value } };
}

/** `?status=` of the one-file page: anything but "reviewed" means open. */
export function parseStatus(value: string | null): 'open' | 'reviewed' {
  return value === 'reviewed' ? 'reviewed' : 'open';
}
