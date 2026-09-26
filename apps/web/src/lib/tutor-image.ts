// Client-side checks for an image attached to a tutor question (ADR 0025).
// Pure for node --test. The API re-checks everything by content; this only
// saves an upload that would be refused anyway.

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const;
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;

/** Why a chosen file cannot be attached, or null when it may be uploaded. */
export function imageProblem(type: string, size: number, name = ''): string | null {
  if (/\.dcm$/i.test(name) || type === 'application/dicom') {
    return 'DICOM files are not accepted. Attach a PNG, JPEG, or WebP screenshot with no patient identifiers.';
  }
  if (!(IMAGE_TYPES as readonly string[]).includes(type)) return 'Attach a PNG, JPEG, or WebP image.';
  if (size <= 0) return 'That file is empty.';
  if (size > MAX_IMAGE_BYTES) return 'Images must be 20 MB or smaller.';
  return null;
}

/** The image id from an upload response body, or null. */
export function uploadedId(body: unknown): string | null {
  const id = body && typeof body === 'object' ? (body as Record<string, unknown>).image_id : null;
  return typeof id === 'string' && /^[0-9a-f-]{36}$/i.test(id) ? id : null;
}
