// Progress insights: heatmap colour scale, projection and calibration copy.
// Pure for node --test. Colours are theme tokens mixed in CSS, so the same
// scale works in light and dark themes; every cell also prints its value, so
// colour is never the only carrier of meaning. No pass probability anywhere.
import type { Calibration, HeatmapCell, Projection } from './types/session.ts';

/** Five-step scale: 0 empty … 4 fully covered; null means no mapped material. */
export function coverageLevel(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.round(Math.min(Math.max(value, 0), 1) * 4);
}

const MIX = [6, 16, 26, 36, 46];

/** Inline style for a cell: the ok colour mixed into the surface, capped so text stays legible. */
export function cellStyle(value: number | null | undefined): string {
  const level = coverageLevel(value);
  if (level === null) return 'background-color: var(--surface-2)';
  return `background-color: color-mix(in oklab, var(--ok) ${MIX[level]}%, var(--surface))`;
}

export function pct(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%`;
}

/** Accessible label for one cell (also its tooltip). */
export function cellLabel(system: string, cell: HeatmapCell): string {
  if (cell.coverage === null) return `${system} · ${cell.title}: no mapped passages yet`;
  const accuracy = cell.accuracy === null ? '' : `, accuracy ${pct(cell.accuracy)}`;
  return `${system} · ${cell.title}: ${pct(cell.coverage)} covered (${cell.studied}/${cell.material} passages)${accuracy}`;
}

export interface Copy {
  headline: string;
  detail: string;
  tone: 'ok' | 'warn' | 'info';
}

function hours(value: number | null): string {
  if (value === null) return '—';
  return value < 1 ? `${Math.round(value * 60)} min` : `${value.toFixed(1)} h`;
}

export function projectionCopy(p: Projection): Copy {
  const target = `${p.target_days} day${p.target_days === 1 ? '' : 's'}`;
  if (p.status === 'done') {
    return { headline: 'Coverage goal reached', detail: 'Keep reviews and mock papers going until the exam.', tone: 'ok' };
  }
  if (p.status === 'insufficient_history') {
    return {
      headline: 'Pace appears after a few completed sessions',
      detail: `Complete Today sessions on at least two days, a few days apart, to measure your pace. ${p.topics_remaining} weighted topic${p.topics_remaining === 1 ? '' : 's'} still below ${pct(p.goal)} coverage.`,
      tone: 'info'
    };
  }
  const needed = `About ${hours(p.needed_hours_per_day)} a day reaches ${pct(p.goal)} coverage in ${target}, 30 days before the exam.`;
  if (p.status === 'on_track') {
    return { headline: `On pace: ${pct(p.projected_coverage)} coverage projected by exam day`, detail: needed, tone: 'ok' };
  }
  return { headline: `Behind pace: ${pct(p.projected_coverage)} coverage projected by exam day`, detail: needed, tone: 'warn' };
}

export function calibrationCopy(c: Calibration): Copy {
  if (c.verdict === 'insufficient') {
    return {
      headline: 'Rate your confidence on SBA answers',
      detail: `Calibration appears after ${c.min_rated} rated answers (${c.rated} so far).`,
      tone: 'info'
    };
  }
  const bias = c.bias === null ? '' : ` (bias ${c.bias > 0 ? '+' : ''}${Math.round(c.bias * 100)} points)`;
  const wrong = c.confident_wrong ? ` ${c.confident_wrong} wrong answer${c.confident_wrong === 1 ? ' was' : 's were'} rated high confidence: review those first.` : '';
  if (c.verdict === 'overconfident') return { headline: `Overconfident${bias}`, detail: `You are right less often than you feel.${wrong}`, tone: 'warn' };
  if (c.verdict === 'underconfident') return { headline: `Underconfident${bias}`, detail: `You know more than you think.${wrong}`, tone: 'info' };
  return { headline: `Well calibrated${bias}`, detail: `Confidence matches results.${wrong}`, tone: 'ok' };
}
