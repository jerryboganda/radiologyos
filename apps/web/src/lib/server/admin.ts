// Admin API client: embedding budget usage and its alerts, model usage, and
// library pipeline controls (org_admin / superadmin).
import type { RequestEvent } from '@sveltejs/kit';
import { isKind, loadProblem, type LoadProblem } from '$lib/api-state';
import { isAdminRole, isEmbeddingUsage, selectBanner } from '$lib/admin-usage';
import { isModelUsage } from '$lib/model-usage';
import { isPipelineStatus } from '$lib/pipeline-control';
import type { AdminBanner, EmbeddingUsage, ModelUsage, PipelineStatus } from '$lib/types/admin';
import { getJson, sendJson, type CallOptions } from './client';

/** The shell check must never hold a page back for long. */
const BANNER_TIMEOUT_MS = 1500;

export const getEmbeddingUsage = (event: RequestEvent, options?: CallOptions) =>
  getJson<EmbeddingUsage>(event, '/v1/admin/embedding-usage', options);

/** 204 on success. */
export const acknowledgeAlert = (event: RequestEvent, id: string) =>
  sendJson<void>(event, `/v1/admin/alerts/${encodeURIComponent(id)}/ack`, 'POST');

export type UsageCard = { usage: EmbeddingUsage; problem: null } | { usage: null; problem: LoadProblem };

/**
 * Settings card data. null hides the card: the session role is not an admin
 * role (skips a pointless call) or the API answered 403.
 */
export async function loadUsageCard(event: RequestEvent): Promise<UsageCard | null> {
  if (!isAdminRole(event.locals.user?.tenantRole)) return null;
  const result = await getEmbeddingUsage(event);
  if (isKind(result, 'forbidden')) return null;
  if (result.state !== 'ok') return { usage: null, problem: loadProblem(result) ?? { offline: true, message: '' } };
  if (!isEmbeddingUsage(result.data)) {
    return { usage: null, problem: { offline: false, message: 'The usage report had an unexpected format.' } };
  }
  return { usage: result.data, problem: null };
}

export const getModelUsage = (event: RequestEvent, options?: CallOptions) =>
  getJson<ModelUsage>(event, '/v1/admin/model-usage', options);

export type ModelUsageCard = { usage: ModelUsage; problem: null } | { usage: null; problem: LoadProblem };

/** Settings card for the model-call ledger (ADR 0032); null hides it (not an admin, or 403). */
export async function loadModelUsageCard(event: RequestEvent): Promise<ModelUsageCard | null> {
  if (!isAdminRole(event.locals.user?.tenantRole)) return null;
  const result = await getModelUsage(event);
  if (isKind(result, 'forbidden')) return null;
  if (result.state !== 'ok') return { usage: null, problem: loadProblem(result) ?? { offline: true, message: '' } };
  if (!isModelUsage(result.data)) {
    return { usage: null, problem: { offline: false, message: 'The model usage report had an unexpected format.' } };
  }
  return { usage: result.data, problem: null };
}

export const getPipelineStatus = (event: RequestEvent, options?: CallOptions) =>
  getJson<PipelineStatus>(event, '/v1/admin/pipeline', options);

/** 204 on success. */
export const pausePipeline = (event: RequestEvent) => sendJson<void>(event, '/v1/admin/pipeline/pause', 'POST');
/** 204 on success. */
export const resumePipeline = (event: RequestEvent) => sendJson<void>(event, '/v1/admin/pipeline/resume', 'POST');
/** 202: the worker redoes the waiting items on Claude Opus (spends the owner's Claude quota). */
export const approvePipeline = (event: RequestEvent) => sendJson<{ status: string }>(event, '/v1/admin/pipeline/approve', 'POST');
/** Closes the waiting items without using Claude. */
export const dismissPipeline = (event: RequestEvent) => sendJson<{ dismissed: number }>(event, '/v1/admin/pipeline/dismiss', 'POST');

export type PipelineCard = { status: PipelineStatus; problem: null } | { status: null; problem: LoadProblem };

/** Settings card for library processing (ADR 0037); null hides it (not an admin, or 403). */
export async function loadPipelineCard(event: RequestEvent): Promise<PipelineCard | null> {
  if (!isAdminRole(event.locals.user?.tenantRole)) return null;
  const result = await getPipelineStatus(event);
  if (isKind(result, 'forbidden')) return null;
  if (result.state !== 'ok') return { status: null, problem: loadProblem(result) ?? { offline: true, message: '' } };
  if (!isPipelineStatus(result.data)) {
    return { status: null, problem: { offline: false, message: 'The processing report had an unexpected format.' } };
  }
  return { status: result.data, problem: null };
}

/**
 * The app-shell banner, or null for non-admins and on any failure (403, 404,
 * network, timeout, unexpected body). Never throws.
 */
export async function loadAdminBanner(event: RequestEvent): Promise<AdminBanner | null> {
  if (!isAdminRole(event.locals.user?.tenantRole)) return null;
  try {
    const result = await getEmbeddingUsage(event, { timeoutMs: BANNER_TIMEOUT_MS });
    return result.state === 'ok' && isEmbeddingUsage(result.data) ? selectBanner(result.data) : null;
  } catch {
    return null;
  }
}
