// Viva and staged image-case helpers: form parsing, staged-answer text, labels.
// Pure for node --test. The staged-answer format mirrors
// packages/assessment/staged_case.py (compose_answer / split_answer).
import type { VivaCreateIn, VivaKind, VivaSession, VivaStyle } from './types/viva.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KINDS: VivaKind[] = ['viva', 'image_case'];
const STYLES: VivaStyle[] = ['practice', 'fcps2_toacs', 'frcr_2b_oral'];

export const STAGES = ['describe', 'findings', 'diagnosis', 'differentials', 'next_step'] as const;
export type Stage = (typeof STAGES)[number];
export const STAGE_LABELS: Record<Stage, string> = {
  describe: 'Describe',
  findings: 'Key findings',
  diagnosis: 'Most likely diagnosis',
  differentials: 'Differentials',
  next_step: 'Next step'
};

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

function intIn(raw: FormDataEntryValue | null, min: number, max: number): number | null | 'bad' {
  const text = String(raw ?? '').trim();
  if (!text) return null;
  const value = Number(text);
  return Number.isInteger(value) && value >= min && value <= max ? value : 'bad';
}

function idOf(raw: FormDataEntryValue | null): string | null | 'bad' {
  const text = String(raw ?? '').trim();
  if (!text) return null;
  return UUID.test(text) ? text : 'bad';
}

/** Validate the start form; the API re-validates everything. */
export function parseStartForm(form: FormData): Parsed<VivaCreateIn> {
  const kind = String(form.get('kind') ?? 'viva') as VivaKind;
  const style = String(form.get('style') ?? 'practice') as VivaStyle;
  if (!KINDS.includes(kind)) return { ok: false, error: 'Choose a viva or an image case.' };
  if (!STYLES.includes(style)) return { ok: false, error: 'Choose a format.' };
  const topic = String(form.get('topic') ?? '').trim().slice(0, 200);
  const figure = idOf(form.get('figure_id'));
  const question = idOf(form.get('question_id'));
  if (figure === 'bad' || question === 'bad') return { ok: false, error: 'That image link is not valid.' };
  if (question && kind !== 'image_case') return { ok: false, error: 'A bank question starts a staged image case.' };
  if (topic.length < 2 && !figure && !question) return { ok: false, error: 'Give a topic (at least two characters).' };
  const turns = intIn(form.get('max_turns'), 2, 20);
  const minutes = intIn(form.get('time_limit_minutes'), 1, 90);
  if (turns === 'bad') return { ok: false, error: 'Questions must be between 2 and 20.' };
  if (minutes === 'bad') return { ok: false, error: 'The time limit must be 1 to 90 minutes.' };
  return {
    ok: true,
    value: {
      kind,
      style,
      topic: topic.length >= 2 ? topic : null,
      figure_id: figure,
      question_id: question,
      max_turns: kind === 'viva' ? turns : null,
      time_limit_minutes: minutes
    }
  };
}

/** One structured answer from per-stage text, for staged cases inside an exam. */
export function composeStaged(parts: Partial<Record<string, string>>): string {
  return STAGES.filter((s) => (parts[s] ?? '').trim())
    .map((s) => `[${s}]\n${(parts[s] ?? '').trim()}`)
    .join('\n');
}

/** Inverse of composeStaged; text before the first heading is ignored. */
export function splitStaged(text: string): Partial<Record<Stage, string>> {
  const heading = /^\[(describe|findings|diagnosis|differentials|next_step)\]\s*$/gm;
  const marks = [...text.matchAll(heading)];
  const out: Partial<Record<Stage, string>> = {};
  marks.forEach((match, i) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = i + 1 < marks.length ? (marks[i + 1].index ?? text.length) : text.length;
    const body = text.slice(start, end).trim();
    if (body) out[match[1] as Stage] = body;
  });
  return out;
}

/** True while the examiner is working and the page should poll. */
export function isWaiting(session: Pick<VivaSession, 'status' | 'work'>): boolean {
  return session.status === 'preparing' || (session.status === 'active' && session.work !== 'none');
}

export const STOP_REASONS: Record<string, string> = {
  max_turns: 'All questions asked',
  time_up: 'Time is up',
  two_consecutive_misses: 'Stopped after two consecutive misses',
  ended_by_candidate: 'Ended by you',
  stages_complete: 'All stages answered',
  examiner_error: 'Stopped: the examiner could not continue'
};

const ERRORS: Record<string, string> = {
  no_source_material: 'Nothing in your processed sources matched that topic yet.',
  no_described_figure: 'No described figure matched. Try a different topic, or start from a figure.',
  figure_not_found: 'That figure is not in your library.',
  question_not_found: 'That question is not in your bank.',
  question_not_staged: 'That question has no staged rubric. Start from its figure instead.',
  question_in_open_exam: 'That question is part of an exam you have not submitted yet.',
  viva_examiner_busy: 'The examiner is still marking your last answer.',
  viva_turn_closed: 'That question has already been answered.',
  viva_not_active: 'This session has ended.',
  viva_time_expired: 'Time ran out before that answer arrived; your session has been marked.'
};

export function vivaError(detail: string): string {
  return ERRORS[detail] ?? detail;
}

export const VERDICT_TONE: Record<string, string> = {
  good: 'border-ok/40 bg-ok-soft text-ok',
  partial: 'border-warn/40 bg-warn-soft text-warn',
  miss: 'border-danger/40 bg-danger-soft text-danger'
};

export const VERDICT_LABEL: Record<string, string> = { good: 'Good', partial: 'Partly there', miss: 'Missed' };

export function styleLabel(style: string): string {
  return { practice: 'Practice viva', fcps2_toacs: 'FCPS-II TOACS', frcr_2b_oral: 'FRCR 2B oral' }[style] ?? style;
}

/** Percent for a score out of a maximum, one decimal; 0 when there is no maximum. */
export function percentOf(score: number, max: number): number {
  return max > 0 ? Math.round((1000 * score) / max) / 10 : 0;
}
