// Today session runner helpers: step copy, progress, SBA navigation, form parsing.
// Pure for node --test.
import type { SbaBlockView, SessionStep, SessionSummary, StepAnswerIn, StudySession } from './types/session.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const STEP_TITLES: Record<string, string> = {
  review: 'Review due cards',
  learn: 'Learn',
  test: 'Timed SBA block',
  viva: 'Viva prompt'
};

export function stepTitle(step: Pick<SessionStep, 'kind' | 'learn'>): string {
  if (step.kind === 'learn' && step.learn?.topic) return `Learn: ${step.learn.topic.title}`;
  return STEP_TITLES[step.kind] ?? step.kind;
}

export function isFinished(step: Pick<SessionStep, 'status'>): boolean {
  return step.status === 'done' || step.status === 'skipped';
}

/** Whole-number percent of steps finished (done or skipped). */
export function progressPercent(session: Pick<StudySession, 'progress'>): number {
  const { done, total } = session.progress;
  return total > 0 ? Math.round((Math.min(done, total) / total) * 100) : 0;
}

/** The step to show: the requested one if it exists, else the one to resume, else the last. */
export function selectedStep(session: Pick<StudySession, 'steps' | 'current_step'>, requested?: number | null): SessionStep | null {
  const steps = session.steps;
  const wanted = requested ?? session.current_step;
  return steps.find((s) => s.step_no === wanted) ?? steps[steps.length - 1] ?? null;
}

/** The first unanswered question after `afterId` (wrapping), or null when all are answered. */
export function nextUnanswered(block: Pick<SbaBlockView, 'questions' | 'results'>, afterId: string | null = null): string | null {
  const answered = new Set(block.results.map((r) => r.question_id));
  const ids = block.questions.map((q) => q.id);
  const start = afterId ? ids.indexOf(afterId) + 1 : 0;
  const order = [...ids.slice(start), ...ids.slice(0, start)];
  return order.find((id) => !answered.has(id)) ?? null;
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

export interface StepRef {
  sessionId: string;
  stepNo: number;
}

export function parseStepRef(form: FormData): Parsed<StepRef> {
  const sessionId = String(form.get('session_id') ?? '');
  const stepNo = Number(form.get('step_no') ?? '');
  if (!UUID.test(sessionId)) return { ok: false, error: 'Unknown session.' };
  if (!Number.isInteger(stepNo) || stepNo < 1 || stepNo > 20) return { ok: false, error: 'Unknown step.' };
  return { ok: true, value: { sessionId, stepNo } };
}

/** An SBA answer (question, option A–E, optional confidence 1–3) or a viva answer text. */
export function parseAnswerForm(form: FormData): Parsed<StepAnswerIn> {
  const text = String(form.get('answer_text') ?? '').trim();
  if (form.has('answer_text')) {
    if (!text) return { ok: false, error: 'Write your answer first.' };
    return { ok: true, value: { answer_text: text.slice(0, 8000) } };
  }
  const questionId = String(form.get('question_id') ?? '');
  const option = Number(form.get('selected_option') ?? '');
  if (!UUID.test(questionId)) return { ok: false, error: 'Unknown question.' };
  if (!form.has('selected_option') || !Number.isInteger(option) || option < 0 || option > 4) {
    return { ok: false, error: 'Choose an option (A–E).' };
  }
  const raw = String(form.get('confidence') ?? '');
  const confidence = raw === '' ? null : Number(raw);
  if (confidence !== null && ![1, 2, 3].includes(confidence)) return { ok: false, error: 'Confidence is 1, 2 or 3.' };
  return { ok: true, value: { question_id: questionId, selected_option: option, confidence } };
}

/** One plain sentence for the completion card. */
export function summaryLine(summary: SessionSummary): string {
  const parts = [`${summary.steps_done} of ${summary.steps_total} steps done`];
  if (summary.reviews) parts.push(`${summary.reviews} card${summary.reviews === 1 ? '' : 's'} reviewed`);
  if (summary.sba_answered) parts.push(`${summary.sba_correct}/${summary.sba_answered} SBA correct`);
  if (summary.viva_answered) parts.push('viva answered');
  if (summary.minutes) parts.push(`about ${summary.minutes} min`);
  return `${parts.join(' · ')}.`;
}

export const CONFIDENCE = [
  { level: 1, label: 'Low' },
  { level: 2, label: 'Medium' },
  { level: 3, label: 'High' }
] as const;
