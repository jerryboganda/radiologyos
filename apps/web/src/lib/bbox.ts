// Normalised bounding boxes ([x0, y0, x1, y1], 0..1, origin top-left) as
// percentage CSS, so overlays stay aligned at any zoom level.
export type BBox = [number, number, number, number];

function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

/** Validate and normalise an API bbox; returns null for anything unusable. */
export function parseBBox(value: unknown): BBox | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  if (!value.every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
  const [a, b, c, d] = value.map(clamp01) as BBox;
  const box: BBox = [Math.min(a, c), Math.min(b, d), Math.max(a, c), Math.max(b, d)];
  if (box[2] - box[0] <= 0 || box[3] - box[1] <= 0) return null;
  return box;
}

function pct(value: number): string {
  return `${Number((value * 100).toFixed(3))}%`;
}

/** `left/top/width/height` in percent of the page image, or null if invalid. */
export function bboxToStyle(value: unknown): string | null {
  const box = parseBBox(value);
  if (!box) return null;
  const [x0, y0, x1, y1] = box;
  return `left:${pct(x0)};top:${pct(y0)};width:${pct(x1 - x0)};height:${pct(y1 - y0)}`;
}

/** Scroll offset (in rendered pixels) that centres a box in a viewport. */
export function bboxCenter(
  value: unknown,
  renderedWidth: number,
  renderedHeight: number
): { x: number; y: number } | null {
  const box = parseBBox(value);
  if (!box) return null;
  return {
    x: ((box[0] + box[2]) / 2) * renderedWidth,
    y: ((box[1] + box[3]) / 2) * renderedHeight
  };
}
