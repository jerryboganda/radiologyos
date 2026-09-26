// Exam results review (ADR 0029): per-item timing, confidence, calibration text,
// and grade-dispute forms. Pure for node --test.
import type { Changes } from './exam-session.ts';
import type { Parsed } from './questions.ts';
import type { DisputeIn, DisputeOut, DisputeResolveIn, ExamCalibration } from './types/results.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_ITEM_SECONDS = 6 * 60 * 60;

/** Per-item seconds only grow: keep the larger count for each item. */
export function mergeSeconds(a: Record<string, number>, b: Record<string, number>): Record<string, number> {
  const merged = { ...a };
  for (const [id, seconds] of Object.entries(b)) {
    const value = Math.min(MAX_ITEM_SECONDS, Math.max(0, Math.floor(seconds)));
    merged[id] = Math.max(merged[id] ?? 0, value);
  }
  return merged;
}

/** Items whose local count moved past the saved one (what the next save must send). */
export function secondsChanges(saved: Record<string, number>, local: Record<string, number>): Record<string, number> {
  const changes: Record<string, number> = {};
  for (const [id, seconds] of Object.entries(local)) {
    if (seconds > (saved[id] ?? 0)) changes[id] = seconds;
  }
  return changes;
}

/** Apply sent changes (null clears) to a saved map. */
export function applyChanges(base: Record<string, number>, changes: Changes): Record<string, number> {
  const next = { ...base };
  for (const [id, value] of Object.entries(changes)) {
    if (value === null) delete next[id];
    else next[id] = value;
  }
  return next;
}

/**
 * Active time per item: the clock runs for the item on screen while the page is
 * visible, and pauses otherwise. Times are in milliseconds from a monotonic source.
 */
export class ItemClock {
  private totals: Record<string, number>;
  private current: string | null = null;
  private since = 0;

  constructor(initialSeconds: Record<string, number> = {}) {
    this.totals = Object.fromEntries(Object.entries(initialSeconds).map(([id, s]) => [id, s * 1000]));
  }

  /** Start timing `id` (stopping whatever was being timed). */
  enter(id: string, now: number): void {
    this.pause(now);
    this.current = id;
    this.since = now;
  }

  /** Stop timing; `enter` or `resume` starts again. */
  pause(now: number): void {
    if (this.current !== null) {
      this.totals[this.current] = (this.totals[this.current] ?? 0) + Math.max(0, now - this.since);
    }
    this.since = now;
    this.current = null;
  }

  /** Whole seconds per item, counting the running interval. */
  seconds(now: number): Record<string, number> {
    const out: Record<string, number> = {};
    for (const [id, ms] of Object.entries(this.totals)) out[id] = Math.floor(ms / 1000);
    if (this.current !== null) {
      const running = (this.totals[this.current] ?? 0) + Math.max(0, now - this.since);
      out[this.current] = Math.floor(running / 1000);
    }
    return out;
  }
}

/** "45s", "3m 05s", "1h 02m". */
export function formatSeconds(total: number | null | undefined): string {
  if (typeof total !== 'number' || !Number.isFinite(total) || total < 0) return '—';
  const s = Math.floor(total);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  return `${m}m ${String(s % 60).padStart(2, '0')}s`;
}

export const CONFIDENCE_LABELS: Record<number, string> = { 1: 'Low', 2: 'Medium', 3: 'High' };

/** A plain reading of the exam's calibration; never a pass probability. */
export function calibrationText(cal: ExamCalibration | undefined): string {
  if (!cal || cal.rated === 0) return 'Rate your confidence (1–3) during an exam to see calibration here.';
  if (cal.bias === null) return 'No rated items have been graded yet.';
  const points = Math.round(Math.abs(cal.bias) * 100);
  if (cal.bias > 0.1) return `Overconfident: you rated yourself about ${points} points above what you scored.`;
  if (cal.bias < -0.1) return `Underconfident: you scored about ${points} points above your stated confidence.`;
  return 'Well calibrated: your confidence matched your marks.';
}

/** The dispute on one scheme point, if any. */
export function disputeFor(disputes: DisputeOut[], questionId: string, pointIndex: number): DisputeOut | null {
  return disputes.find((d) => d.question_id === questionId && d.point_index === pointIndex) ?? null;
}

export function parseDisputeForm(form: FormData): Parsed<DisputeIn> {
  const questionId = String(form.get('question_id') ?? '');
  const index = Number(form.get('point_index'));
  const reason = String(form.get('reason') ?? '').trim();
  if (!UUID.test(questionId) || !Number.isInteger(index) || index < 0 || index > 99) {
    return { ok: false, error: 'Unknown marking point.' };
  }
  if (!reason) return { ok: false, error: 'Say why this point deserves more marks.' };
  if (reason.length > 2000) return { ok: false, error: 'Keep the reason under 2000 characters.' };
  return { ok: true, value: { question_id: questionId, point_index: index, reason } };
}

export function parseResolveForm(form: FormData): Parsed<DisputeResolveIn & { id: string }> {
  const id = String(form.get('dispute_id') ?? '');
  const action = String(form.get('action') ?? '');
  if (!UUID.test(id) || (action !== 'accept' && action !== 'reject')) return { ok: false, error: 'Unknown dispute action.' };
  const note = String(form.get('note') ?? '').trim();
  if (note.length > 2000) return { ok: false, error: 'Keep the note under 2000 characters.' };
  const raw = String(form.get('awarded') ?? '').trim();
  const awarded = raw ? Number(raw) : null;
  if (awarded !== null && (!Number.isFinite(awarded) || awarded <= 0 || awarded > 10)) {
    return { ok: false, error: 'The new award must be above zero and at most the point’s marks.' };
  }
  return { ok: true, value: { id, action, awarded: action === 'accept' ? awarded : null, note } };
}

const DISPUTE_ERRORS: Record<string, string> = {
  already_disputed: 'You have already disputed this point.',
  point_has_full_marks: 'This point already has full marks.',
  item_not_graded: 'This answer has not been graded yet.',
  exam_not_submitted: 'Submit the exam before disputing a grade.',
  dispute_closed: 'This dispute has already been resolved.',
  point_changed_since_dispute: 'The point was re-marked after the dispute; reject it and ask for a new one.',
  award_out_of_range: 'The new award must be above the original and at most the point’s marks.'
};

export function disputeMessage(detail: string): string {
  return DISPUTE_ERRORS[detail] ?? 'The dispute could not be saved.';
}
