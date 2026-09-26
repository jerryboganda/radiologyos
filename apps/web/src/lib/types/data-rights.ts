// Data-rights API contract (apps/api/app/api/data_rights.py, ADR 0018).
export type DataJobKind = 'export' | 'delete';
export type DataJobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface DataJob {
  id: string;
  kind: DataJobKind;
  status: DataJobStatus;
  step: string;
  byte_size: number | null;
  /** Counts and ids only (never content). */
  detail: Record<string, unknown>;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
  expires_at: string | null;
  /** API path of the ZIP once built; the browser downloads it via /settings/exports/{id}. */
  download_path: string | null;
}

/** DELETE /v1/me body. The API compares case-insensitively after trimming. */
export interface DeleteAccountRequest {
  confirmation: string;
}

export const DELETE_CONFIRMATION = 'delete my account';
