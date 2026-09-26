// Client-side upload checks. The API detects formats by content and remains
// authoritative; these checks only give fast, friendly feedback.
export const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'pptx', 'jpg', 'jpeg', 'png'] as const;
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

/** Cloudflare rejects request bodies over 100 MB on the public hostname. */
export const TUNNEL_LIMIT_BYTES = 100 * 1024 * 1024;
/** The API's configured maximum (`max_upload_bytes`, 300 MiB). */
export const API_LIMIT_BYTES = 300 * 1024 * 1024;

export type UploadCheck =
  | { ok: true; warning: string | null }
  | { ok: false; reason: string };

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

export function checkUpload(name: string, size: number): UploadCheck {
  const ext = extensionOf(name);
  if (ext === 'dcm' || ext === 'dicom') {
    return { ok: false, reason: 'DICOM files are not accepted. Export key images as PNG or JPEG.' };
  }
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
    return { ok: false, reason: 'Unsupported type. Use PDF, DOCX, PPTX, JPEG, or PNG.' };
  }
  if (size <= 0) return { ok: false, reason: 'This file is empty.' };
  if (size > API_LIMIT_BYTES) return { ok: false, reason: 'Larger than the 300 MB upload limit.' };
  if (size > TUNNEL_LIMIT_BYTES) {
    return {
      ok: true,
      warning: 'Over 100 MB: the public site (Cloudflare) will reject this. Split the file or upload on the local network.'
    };
  }
  return { ok: true, warning: null };
}

/** Friendly message for an upload response status. */
export function uploadErrorMessage(status: number, detail?: string | null): string {
  if (status === 413) return 'Too large for the upload path (Cloudflare allows 100 MB; the API 300 MB).';
  if (status === 415) return detail ? `Not accepted: ${detail}` : 'This file type is not accepted.';
  if (status === 401) return 'Your session has expired. Sign in again.';
  if (status === 0) return 'Network error — check your connection and retry.';
  if (status >= 500) return 'The server could not store this file. Try again shortly.';
  return detail || `Upload failed (${status}).`;
}
