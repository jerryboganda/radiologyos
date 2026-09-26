// Grade dispute API client (apps/api/app/api/disputes.py, ADR 0029).
import type { RequestEvent } from '@sveltejs/kit';
import type { DisputeIn, DisputeOut, DisputeQueueItem, DisputeResolveIn, DisputeResolved } from '$lib/types/results';
import { getJson, query, sendJson } from './client';

const examPath = (examId: string) => `/v1/exams/${encodeURIComponent(examId)}/disputes`;

/** The caller's disputes on one of their exams. */
export const listDisputes = (event: RequestEvent, examId: string) => getJson<DisputeOut[]>(event, examPath(examId));

/** 409 `already_disputed` / `point_has_full_marks` / `item_not_graded`; 404 unknown point. */
export const openDispute = (event: RequestEvent, examId: string, body: DisputeIn) =>
  sendJson<DisputeOut>(event, examPath(examId), 'POST', body);

/** Owner/admin only (403 otherwise): the tenant's open disputes, oldest first. */
export const disputeQueue = (event: RequestEvent, limit = 50) =>
  getJson<DisputeQueueItem[]>(event, `/v1/grade-disputes/review${query({ limit })}`);

/** Owner/admin only: accept (adjusts the score, audited) or reject. */
export const resolveDispute = (event: RequestEvent, disputeId: string, body: DisputeResolveIn) =>
  sendJson<DisputeResolved>(event, `/v1/grade-disputes/${encodeURIComponent(disputeId)}/resolve`, 'POST', body);
