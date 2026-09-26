// Small display formatters. Pure for node --test.

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Whole days from `today` to `examDate` (YYYY-MM-DD); null when unknown. */
export function daysUntil(examDate: string | null | undefined, today = new Date()): number | null {
  if (!examDate || !/^\d{4}-\d{2}-\d{2}$/.test(examDate)) return null;
  const target = Date.UTC(+examDate.slice(0, 4), +examDate.slice(5, 7) - 1, +examDate.slice(8, 10));
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - start) / 86_400_000);
}

export function percent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%`;
}

/** One-decimal percentage for small shares such as topic weights (0.034 → "3.4%"). */
export function percentFine(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${(Math.min(Math.max(value, 0), 1) * 100).toFixed(1)}%`;
}

function terms(query: string): string[] {
  return [...new Set(query.toLowerCase().split(/\s+/).filter((t) => t.length >= 2))];
}

/** A window of `text` around the first query term match, with ellipses. */
export function snippet(text: string, query: string, max = 280): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (clean.length <= max) return clean;
  const lower = clean.toLowerCase();
  const hit = terms(query)
    .map((t) => lower.indexOf(t))
    .filter((i) => i >= 0)
    .sort((a, b) => a - b)[0];
  const start = hit === undefined ? 0 : Math.max(0, Math.min(hit - Math.floor(max / 3), clean.length - max));
  const body = clean.slice(start, start + max).trim();
  return `${start > 0 ? '…' : ''}${body}${start + max < clean.length ? '…' : ''}`;
}

export interface TextPart {
  text: string;
  match: boolean;
}

/** Split text into parts, marking case-insensitive query term matches. */
export function highlight(text: string, query: string): TextPart[] {
  const list = terms(query).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!list.length) return [{ text, match: false }];
  const pattern = new RegExp(`(${list.join('|')})`, 'gi');
  return text
    .split(pattern)
    .filter((part) => part.length > 0)
    .map((part) => ({ text: part, match: list.some((t) => new RegExp(`^${t}$`, 'i').test(part)) }));
}
