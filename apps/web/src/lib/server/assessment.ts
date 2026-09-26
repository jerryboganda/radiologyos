// Assessment API client (apps/api/app/api/assessment.py).
import type { RequestEvent } from '@sveltejs/kit';
import type {
  AttemptIn,
  AttemptOut,
  AutosaveIn,
  AutosaveOut,
  BlueprintOut,
  BlueprintOverrideIn,
  ExamCreate,
  ExamView,
  GenerateQuestionsIn,
  GenerateQuestionsOut,
  QuestionPublic,
  ReviewIn,
  ReviewItem,
  ReviewOut,
  StatsRecomputeOut
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

/** The owner's draft questions in full (keys, schemes, checker reasons). */
export const reviewQueue = (event: RequestEvent, limit = 20) =>
  getJson<ReviewItem[]>(event, `/v1/questions/review${query({ limit })}`);

/** 409 `citations_stale` / `not_a_draft`; 422 with comma-joined check codes. */
export const reviewQuestion = (event: RequestEvent, questionId: string, body: ReviewIn) =>
  sendJson<ReviewOut>(event, `/v1/questions/${encodeURIComponent(questionId)}/review`, 'POST', body);

export const recomputeStats = (event: RequestEvent) =>
  sendJson<StatsRecomputeOut>(event, '/v1/questions/stats/recompute', 'POST');

/** Idempotent: later calls return the stored result; written items may stay pending. */
export const submitExam = (event: RequestEvent, examId: string) =>
  sendJson<ExamView>(event, `/v1/exams/${encodeURIComponent(examId)}/submit`, 'POST');

export type ExamSummary = {
  id: string;
  mode: string;
  status: string;
  started_at: string;
  deadline_at: string | null;
  submitted_at: string | null;
  question_count: number;
  answered: number;
  score_percent: number | null;
  pending_grading?: number;
};

export function listExams(event: RequestEvent) {
  return getJson<ExamSummary[]>(event, '/v1/exams');
}

/** Exam blueprints with the tenant's overrides and approval state (ADR 0023). */
export const listBlueprints = (event: RequestEvent) => getJson<BlueprintOut[]>(event, '/v1/blueprints');

/** Owner/admin: replace the override (clears approval). */
export const overrideBlueprint = (event: RequestEvent, id: string, body: BlueprintOverrideIn) =>
  sendJson<BlueprintOut>(event, `/v1/blueprints/${encodeURIComponent(id)}/overrides`, 'PUT', body);

/** Owner/admin: approve the effective blueprint with this hash. */
export const approveBlueprint = (event: RequestEvent, id: string, contentHash: string) =>
  sendJson<BlueprintOut>(event, `/v1/blueprints/${encodeURIComponent(id)}/approve`, 'POST', {
    content_hash: contentHash
  });
