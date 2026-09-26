// Reader helpers: proxy URLs and zoom maths. Pure for node --test.
//
// Zoom "scale" is device pixels per image pixel: 1 means actual pixels, so a
// radiograph is never shown downsampled unless the user chooses "Fit".
export const ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const;

const PAGE_IMAGE = /^\/v1\/library\/sources\/([0-9a-f-]{36})\/pages\/(\d+)\/image$/i;
const FIGURE_IMAGE = /^\/v1\/library\/figures\/([0-9a-f-]{36})\/image$/i;

/** Map an API image path to the same-origin authenticated proxy route. */
export function mediaUrl(apiPath: string | null | undefined): string | null {
  if (!apiPath) return null;
  const page = PAGE_IMAGE.exec(apiPath);
  if (page) return `/media/pages/${page[1]}/${page[2]}`;
  const figure = FIGURE_IMAGE.exec(apiPath);
  if (figure) return `/media/figures/${figure[1]}`;
  return null;
}

export function zoomIn(scale: number): number {
  return ZOOM_STEPS.find((z) => z > scale + 0.001) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]!;
}

export function zoomOut(scale: number): number {
  return [...ZOOM_STEPS].reverse().find((z) => z < scale - 0.001) ?? ZOOM_STEPS[0];
}

/** Scale at which the image exactly fills the container width. */
export function fitScale(containerCssWidth: number, naturalWidth: number, dpr: number): number {
  if (naturalWidth <= 0 || containerCssWidth <= 0) return 1;
  return (containerCssWidth * dpr) / naturalWidth;
}

/** Rendered CSS width for a scale. */
export function cssWidth(naturalWidth: number, scale: number, dpr: number): number {
  return (naturalWidth * scale) / Math.max(dpr, 0.5);
}

/** Parse `?page=` into a positive page number (default 1). */
export function parsePage(value: string | null): number {
  if (!value || !/^\d{1,6}$/.test(value)) return 1;
  return Math.max(1, Number(value));
}

/** Parse `?block=` into a block number or null. */
export function parseBlock(value: string | null): number | null {
  if (!value || !/^\d{1,6}$/.test(value)) return null;
  return Number(value);
}
