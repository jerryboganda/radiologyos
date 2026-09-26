// Draft text while the tutor writes (ADR 0025). Pure for node --test.
// Drafts are unverified and uncited: the page shows them only under a
// "draft, not yet checked" label and replaces them with the judged answer
// (or discards them on an error). They are never stored.

export type DraftPhase = 'sources' | 'web';

export interface Drafts {
  sources: string[];
  web: string[];
}

export const MAX_DRAFT_SEGMENTS = 80;
export const MAX_DRAFT_CHARS = 4000;

export const emptyDrafts = (): Drafts => ({ sources: [], web: [] });

export const hasDrafts = (drafts: Drafts): boolean =>
  drafts.sources.some((s) => s.trim()) || drafts.web.some((s) => s.trim());

function isIndex(value: unknown, limit: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= limit;
}

/**
 * Apply one `draft` operation: `append` to or replace (`text`) segment
 * `segment` of a phase, or shrink the phase to `count` segments. Anything
 * malformed is ignored. Returns a new object so Svelte state updates.
 */
export function applyDraft(drafts: Drafts, op: Record<string, unknown> | null): Drafts {
  const phase: DraftPhase | null = op?.phase === 'web' ? 'web' : op?.phase === 'sources' ? 'sources' : null;
  if (!op || !phase) return drafts;
  const list = [...drafts[phase]];
  if (isIndex(op.count, MAX_DRAFT_SEGMENTS)) {
    list.length = Math.min(list.length, op.count);
  } else if (isIndex(op.segment, MAX_DRAFT_SEGMENTS - 1)) {
    while (list.length <= op.segment) list.push('');
    if (typeof op.text === 'string') list[op.segment] = op.text.slice(0, MAX_DRAFT_CHARS);
    else if (typeof op.append === 'string') list[op.segment] = (list[op.segment] + op.append).slice(0, MAX_DRAFT_CHARS);
    else return drafts;
  } else {
    return drafts;
  }
  return { ...drafts, [phase]: list };
}
