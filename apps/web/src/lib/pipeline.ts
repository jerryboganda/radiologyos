// Ingestion step progress for the library list and reader header.
import type { StepStatus } from './types/library';

export type StepState = 'done' | 'running' | 'waiting' | 'skipped' | 'failed';

/** Display order. `ready` is the worker's `ready_notify` step. */
export const PIPELINE_STEPS = [
  { step: 'render_pages', label: 'Render pages' },
  { step: 'chunk', label: 'Chunk text' },
  { step: 'embed_index', label: 'Index' },
  { step: 'ready_notify', label: 'Searchable' },
  { step: 'parse_layout', label: 'Parse layout' },
  { step: 'extract_figures', label: 'Figures' }
] as const;

export interface StepView {
  step: string;
  label: string;
  state: StepState;
  detail: string | null;
}

export function stepState(status: string | undefined): StepState {
  switch (status) {
    case 'succeeded':
      return 'done';
    case 'running':
      return 'running';
    case 'skipped':
      return 'skipped';
    case 'failed':
      return 'failed';
    default:
      return 'waiting';
  }
}

export function summarizeSteps(steps: StepStatus[]): StepView[] {
  const byName = new Map(steps.map((s) => [s.step, s]));
  return PIPELINE_STEPS.map(({ step, label }) => {
    const found = byName.get(step);
    const state = stepState(found?.status);
    const detail = state === 'skipped' || state === 'failed' ? (found?.error_code ?? null) : null;
    return { step, label, state, detail };
  });
}

const TERMINAL = new Set(['ready', 'failed', 'deleted']);

/**
 * Still worth polling? A source becomes `ready` (searchable) before the
 * vision pass finishes, so running steps also count as processing.
 */
export function isProcessing(status: string, steps?: StepStatus[] | null): boolean {
  if (!TERMINAL.has(status)) return true;
  if (status !== 'ready' || !steps) return false;
  const shown = new Set<string>(PIPELINE_STEPS.map((s) => s.step));
  return steps.some((s) => shown.has(s.step) && (s.status === 'running' || s.status === 'pending'));
}

/** 0..1 share of display steps that are finished (done or skipped). */
export function stepProgress(views: StepView[]): number {
  if (!views.length) return 0;
  const finished = views.filter((v) => v.state === 'done' || v.state === 'skipped').length;
  return finished / views.length;
}
