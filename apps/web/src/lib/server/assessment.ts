// Assessment API client (apps/api/app/api/assessment.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  AttemptIn,
  AttemptOut,
  AutosaveIn,
  AutosaveOut,
  ExamCreate,
  ExamView,
  GenerateQuestionsIn,
  GenerateQuestionsOut,
  QuestionPublic
} from '$lib/types/assessment';
import { getJson, query, sendJson } from './client';

const MODEL_TIMEOUT = 300_000;

export interface QuestionFilters {
  type?: string | null;
  exam_target?: string | null;
  topic?: string | null;
  limit?: number;
  offset?: number;
}

export const listQuestions = (event: RequestEvent, filters: QuestionFilters = {}) =>
  getJson<QuestionPublic[]>(event, `/v1/questions${query({ ...filters })}`);

/** Model-backed: 503 not configured / usage limit, 502 retry, 422 no matching material. */
export const generateQuestions = (event: RequestEvent, body: GenerateQuestionsIn) =>
  sendJson<GenerateQuestionsOut>(event, '/v1/questions/generate', 'POST', body, { timeoutMs: MODEL_TIMEOUT });

/** SBA is graded instantly; SEQ/image/viva are model-graded. 409 while the question is in an open exam. */
export const attempt = (event: RequestEvent, questionId: string, body: AttemptIn) =>
  sendJson<AttemptOut>(event, `/v1/questions/${encodeURIComponent(questionId)}/attempt`, 'POST', body, {
    timeoutMs: MODEL_TIMEOUT
  });

export const createExam = (event: RequestEvent, body: ExamCreate) =>
  sendJson<ExamView>(event, '/v1/exams', 'POST', body);

/** Reading an expired exam finalises (grades) it server-side. */
export const getExam = (event: RequestEvent, examId: string) =>
  getJson<ExamView>(event, `/v1/exams/${encodeURIComponent(examId)}`);

/** Compare-and-set: 409 `stale_revision`, `exam_submitted`, or `exam_time_expired`. */
export const saveAnswers = (event: RequestEvent, examId: string, body: AutosaveIn) =>
  sendJson<AutosaveOut>(event, `/v1/exams/${encodeURIComponent(examId)}/answers`, 'PUT', body);

/** Idempotent: later calls return the stored result. */
export const submitExam = (event: RequestEvent, examId: string) =>
  sendJson<ExamView>(event, `/v1/exams/${encodeURIComponent(examId)}/submit`, 'POST');
