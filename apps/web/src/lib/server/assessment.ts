// Assessment API client (planned: /v1/questions, /v1/exams).
import type { RequestEvent } from '@sveltejs/kit';
import type { AttemptResult, ExamSummary, Question } from '$lib/types/assessment';
import { getJson, sendJson } from './client';

export const listQuestions = (event: RequestEvent, limit = 10) =>
  getJson<Question[]>(event, `/v1/questions?limit=${limit}`);

export const attempt = (event: RequestEvent, questionId: string, choiceIndex: number) =>
  sendJson<AttemptResult>(event, `/v1/questions/${encodeURIComponent(questionId)}/attempts`, 'POST', {
    choice_index: choiceIndex
  });

export const listExams = (event: RequestEvent) => getJson<ExamSummary[]>(event, '/v1/exams');

export const startExam = (event: RequestEvent, examId: string) =>
  sendJson<ExamSummary>(event, `/v1/exams/${encodeURIComponent(examId)}/start`, 'POST');
