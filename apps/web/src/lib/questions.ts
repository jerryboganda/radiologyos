// Question-bank form parsing. Pure for node --test.
import type { ExamCreate, GeneratableType, GenerateQuestionsIn, QuestionType } from './types/assessment.ts';
import { isExamTarget } from './types/study.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TYPES: QuestionType[] = ['sba', 'seq', 'image_case', 'viva', 'rapid_recall'];
const GENERATABLE: GeneratableType[] = ['sba', 'seq', 'image_case', 'viva'];

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

function topicOf(raw: FormDataEntryValue | string | null): string | null {
  const topic = String(raw ?? '').trim().slice(0, 200);
  return topic.length >= 2 ? topic : null;
}

/** Bank filters from the URL; unknown values are dropped rather than sent. */
export function questionFilters(params: URLSearchParams) {
  const type = params.get('type');
  const target = params.get('exam_target');
  return {
    type: TYPES.includes(type as QuestionType) ? (type as QuestionType) : null,
    exam_target: isExamTarget(target) ? target : null,
    topic: topicOf(params.get('topic'))
  };
}

export function parseGenerateForm(form: FormData): Parsed<GenerateQuestionsIn> {
  const type = String(form.get('type') ?? '') as GeneratableType;
  if (!GENERATABLE.includes(type)) return { ok: false, error: 'Choose a question type.' };
  const target = form.get('exam_target');
  if (!isExamTarget(target)) return { ok: false, error: 'Choose an exam.' };
  const count = Number(form.get('count') ?? 3);
  if (!Number.isInteger(count) || count < 1 || count > 5) return { ok: false, error: 'Generate between 1 and 5 questions.' };
  const topic = topicOf(form.get('topic'));
  const sourceIds = [...new Set(form.getAll('source_ids').map(String))].filter((id) => UUID.test(id)).slice(0, 20);
  if (!topic && sourceIds.length === 0) return { ok: false, error: 'Give a topic, choose sources, or both.' };
  return { ok: true, value: { type, exam_target: target, count, topic, source_ids: sourceIds } };
}

export function parseExamForm(form: FormData): Parsed<ExamCreate> {
  const mode = form.get('mode') === 'practice' ? 'practice' : 'exam';
  const count = Number(form.get('count') ?? 20);
  if (!Number.isInteger(count) || count < 1 || count > 200) return { ok: false, error: 'Choose 1–200 questions.' };
  const rawMinutes = String(form.get('time_limit_minutes') ?? '').trim();
  const minutes = rawMinutes ? Number(rawMinutes) : null;
  if (minutes !== null && (!Number.isInteger(minutes) || minutes < 1 || minutes > 300)) {
    return { ok: false, error: 'The time limit must be 1–300 minutes.' };
  }
  if (mode === 'exam' && minutes === null) return { ok: false, error: 'A timed exam needs a time limit.' };
  const target = form.get('exam_target');
  return {
    ok: true,
    value: {
      mode,
      count,
      time_limit_minutes: minutes,
      exam_target: isExamTarget(target) ? target : null,
      topic: topicOf(form.get('topic'))
    }
  };
}

/** Letter label for an option index (A–E). */
export function optionLetter(index: number | null | undefined): string {
  return typeof index === 'number' && index >= 0 && index < 26 ? String.fromCharCode(65 + index) : '—';
}
