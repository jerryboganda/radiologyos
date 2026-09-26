// Viva API client (apps/api/app/api/viva.py). Model work runs in the worker, so
// every call here is quick; the page polls the session while `work` is not `none`.
import type { RequestEvent } from '@sveltejs/kit';
import type { VivaCreateIn, VivaSession, VivaSummary } from '$lib/types/viva';
import { getJson, query, sendJson } from './client';

const path = (id: string) => `/v1/viva/sessions/${encodeURIComponent(id)}`;

export const listVivas = (event: RequestEvent, limit = 30) =>
  getJson<VivaSummary[]>(event, `/v1/viva/sessions${query({ limit })}`);

/** 422 `no_source_material` / `no_described_figure`; 409 `question_in_open_exam`. */
export const createViva = (event: RequestEvent, body: VivaCreateIn) =>
  sendJson<VivaSession>(event, '/v1/viva/sessions', 'POST', body, { timeoutMs: 30_000 });

/** Reading finishes a session whose deadline passed and re-queues stalled work. */
export const getViva = (event: RequestEvent, id: string) => getJson<VivaSession>(event, path(id));

/** 409 `viva_examiner_busy`, `viva_turn_closed`, `viva_not_active`, or `viva_time_expired`. */
export const answerViva = (event: RequestEvent, id: string, turnNo: number, answerText: string) =>
  sendJson<VivaSession>(event, `${path(id)}/turns/${turnNo}/answer`, 'POST', { answer_text: answerText });

/** Idempotent. */
export const endViva = (event: RequestEvent, id: string) => sendJson<VivaSession>(event, `${path(id)}/end`, 'POST');
