// Data-rights and curriculum-review form parsing and display. Pure for node --test.
import { DELETE_CONFIRMATION, type DataJob } from './types/data-rights.ts';
import type { MappingDecision } from './types/knowledge.ts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^[A-Z0-9][A-Z0-9._-]{0,59}$/;

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}

/** Matches the API rule: trimmed, case-insensitive "delete my account". */
export function confirmsDeletion(value: unknown): boolean {
  return typeof value === 'string' && value.trim().toLowerCase() === DELETE_CONFIRMATION;
}

export function parseDeleteForm(form: FormData): Parsed<{ confirmation: string }> {
  const confirmation = String(form.get('confirmation') ?? '');
  if (!confirmsDeletion(confirmation)) {
    return { ok: false, error: `Type “${DELETE_CONFIRMATION}” exactly to confirm.` };
  }
  return { ok: true, value: { confirmation: confirmation.trim() } };
}

export function parseDecisionForm(form: FormData): Parsed<{ mappingId: string; body: MappingDecision }> {
  const mappingId = String(form.get('mapping_id') ?? '');
  if (!isUuid(mappingId)) return { ok: false, error: 'Unknown mapping.' };
  const decision = form.get('decision');
  if (decision === 'accept' || decision === 'reject') return { ok: true, value: { mappingId, body: { decision } } };
  if (decision !== 'code') return { ok: false, error: 'Choose accept, reject, or a different code.' };
  const code = String(form.get('curriculum_code') ?? '').trim().toUpperCase();
  if (!CODE.test(code)) return { ok: false, error: 'Choose a curriculum code.' };
  return { ok: true, value: { mappingId, body: { decision: 'code', curriculum_code: code } } };
}

/** Browser-facing download URL (the web server streams the API bytes). */
export function downloadHref(job: DataJob): string | null {
  return job.kind === 'export' && job.status === 'succeeded' && job.download_path ? `/settings/exports/${job.id}` : null;
}

export function isExpired(job: DataJob, now = new Date()): boolean {
  return job.expires_at !== null && new Date(job.expires_at).getTime() <= now.getTime();
}

const STEPS: Record<string, string> = {
  queued: 'Waiting for the worker',
  building: 'Collecting your data',
  done: 'Ready'
};

/** One short status line for an export job. */
export function exportStatusText(job: DataJob, now = new Date()): string {
  if (job.status === 'failed') {
    return job.error_code === 'account_deleting' ? 'Cancelled: account deletion requested' : 'Failed. Request a new export.';
  }
  if (job.status === 'succeeded') return isExpired(job, now) ? 'Expired' : 'Ready to download';
  if (job.status === 'queued' && job.error_code) return 'Retrying shortly';
  return STEPS[job.step] ?? 'In progress';
}

export function hasActiveExport(jobs: DataJob[]): boolean {
  return jobs.some((job) => job.status === 'queued' || job.status === 'running');
}
