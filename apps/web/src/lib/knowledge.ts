// Knowledge form parsing and display helpers. Pure for node --test.
import type {
  ApproveRequest,
  CurriculumDecision,
  CurriculumFilter,
  ExtractRequest,
  ResolveRequest,
  TrustChoice,
  TrustRequest,
  WeightBasis,
  WeightTarget
} from './types/knowledge.ts';
import { CURRICULUM_FILTERS, WEIGHT_TARGETS } from './types/knowledge.ts';

const TRUST_CHOICES: TrustChoice[] = ['a', 'b', 'both'];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

export function isWeightTarget(value: unknown): value is WeightTarget {
  return WEIGHT_TARGETS.includes(value as WeightTarget);
}

export function parseResolveForm(form: FormData): Parsed<{ conflictId: string; body: ResolveRequest }> {
  const conflictId = String(form.get('conflict_id') ?? '');
  if (!UUID.test(conflictId)) return { ok: false, error: 'Unknown conflict.' };
  const resolution = String(form.get('resolution') ?? '').trim();
  if (!resolution) return { ok: false, error: 'Explain how the sources should be reconciled.' };
  if (resolution.length > 2000) return { ok: false, error: 'Keep the resolution under 2,000 characters.' };
  const preferred = String(form.get('preferred_claim_id') ?? '');
  return {
    ok: true,
    value: { conflictId, body: { resolution, preferred_claim_id: UUID.test(preferred) ? preferred : null } }
  };
}

/** "Trust source A / B / both valid in context" on one conflict (ADR 0030). */
export function parseTrustForm(form: FormData): Parsed<{ conflictId: string; body: TrustRequest }> {
  const conflictId = String(form.get('conflict_id') ?? '');
  if (!UUID.test(conflictId)) return { ok: false, error: 'Unknown conflict.' };
  const trust = String(form.get('trust') ?? '');
  if (!TRUST_CHOICES.includes(trust as TrustChoice)) return { ok: false, error: 'Choose which source to trust.' };
  const note = String(form.get('note') ?? '').trim();
  if (note.length > 1000) return { ok: false, error: 'Keep the note under 1,000 characters.' };
  return { ok: true, value: { conflictId, body: { trust: trust as TrustChoice, note } } };
}

export type MergeAction = 'merge' | 'distinct' | 'undo';

/** Owner decision on a Resolver pair: merge, keep distinct, or undo an applied merge. */
export function parseMergeForm(form: FormData): Parsed<{ mergeId: string; action: MergeAction }> {
  const mergeId = String(form.get('merge_id') ?? '');
  if (!UUID.test(mergeId)) return { ok: false, error: 'Unknown merge decision.' };
  const action = String(form.get('action') ?? '');
  if (action !== 'merge' && action !== 'distinct' && action !== 'undo') return { ok: false, error: 'Choose merge, keep separate, or undo.' };
  return { ok: true, value: { mergeId, action } };
}

/** Verification binds the exact note version the owner read. */
export function parseVerifyForm(form: FormData): Parsed<{ noteId: string }> {
  const noteId = String(form.get('note_id') ?? '');
  if (!UUID.test(noteId)) return { ok: false, error: 'Reload the page and try again.' };
  return { ok: true, value: { noteId } };
}

/** One weight (`weight_id`) or every weight for the target when absent. */
export function parseApproveForm(form: FormData): Parsed<ApproveRequest> {
  const target = form.get('exam_target');
  if (!isWeightTarget(target)) return { ok: false, error: 'Choose which exam’s weights to approve.' };
  const id = String(form.get('weight_id') ?? '');
  if (id && !UUID.test(id)) return { ok: false, error: 'Unknown topic weight.' };
  return { ok: true, value: { exam_target: target, weight_ids: id ? [id] : null } };
}

export function parseExtractForm(form: FormData): Parsed<{ sourceId: string; body: ExtractRequest }> {
  const sourceId = String(form.get('source_id') ?? '');
  if (!UUID.test(sourceId)) return { ok: false, error: 'Choose a source.' };
  const mode = form.get('mode') === 'past_paper' ? 'past_paper' : 'notes';
  const target = form.get('exam_target');
  const rawYear = String(form.get('year') ?? '').trim();
  const year = rawYear ? Number(rawYear) : null;
  if (year !== null && (!Number.isInteger(year) || year < 1990 || year > 2100)) {
    return { ok: false, error: 'Year must be between 1990 and 2100.' };
  }
  const examTarget = isWeightTarget(target) && target !== 'all' ? target : null;
  if (mode === 'past_paper' && !examTarget) return { ok: false, error: 'Say which exam this past paper is from.' };
  return { ok: true, value: { sourceId, body: { mode, exam_target: examTarget, year } } };
}

/** "12 of 240 questions · 5 of 8 papers · 2019–2024" */
export function basisText(basis: WeightBasis | null | undefined): string {
  if (!basis) return '';
  const parts: string[] = [];
  if (typeof basis.count === 'number' && typeof basis.total === 'number') parts.push(`${basis.count} of ${basis.total} questions`);
  if (typeof basis.papers === 'number' && typeof basis.total_papers === 'number') {
    parts.push(`${basis.papers} of ${basis.total_papers} papers`);
  }
  const years = (basis.years ?? []).filter((y) => Number.isInteger(y));
  if (years.length) {
    const first = Math.min(...years);
    const last = Math.max(...years);
    parts.push(first === last ? String(first) : `${first}–${last}`);
  }
  return parts.join(' · ');
}

export function isCurriculumFilter(value: unknown): value is CurriculumFilter {
  return value === 'frcr' || CURRICULUM_FILTERS.some((f) => f.value === value);
}

/** Approve/reject of the exact pack version shown (hash-bound). */
export function parseCurriculumDecisionForm(form: FormData): Parsed<CurriculumDecision> {
  const decision = form.get('decision');
  if (decision !== 'approved' && decision !== 'rejected') return { ok: false, error: 'Choose approve or reject.' };
  const hash = String(form.get('content_hash') ?? '');
  if (!/^[0-9a-f]{64}$/.test(hash)) return { ok: false, error: 'Reload the page and try again.' };
  const notes = String(form.get('notes') ?? '').trim();
  if (notes.length > 2000) return { ok: false, error: 'Keep notes under 2,000 characters.' };
  if (decision === 'rejected' && !notes) return { ok: false, error: 'Say what needs to change before rejecting.' };
  return { ok: true, value: { decision, content_hash: hash, notes } };
}
