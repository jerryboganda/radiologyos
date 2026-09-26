// Exam blueprint display and override-form parsing (ADR 0023). Pure for node --test.
import type { BlueprintOut } from './types/assessment.ts';

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

const TYPE_LABELS: Record<string, string> = {
  sba: 'SBA',
  seq: 'SEQ/SAQ',
  image_case: 'image cases',
  viva: 'viva cases'
};

/** "120 SBA · 180 min" */
export function itemsText(blueprint: Pick<BlueprintOut, 'items' | 'duration_minutes'>): string {
  const parts = Object.entries(blueprint.items)
    .filter(([, n]) => n > 0)
    .map(([type, n]) => `${n} ${TYPE_LABELS[type] ?? type}`);
  return [...parts, `${blueprint.duration_minutes} min`].join(' · ');
}

/** "Negative marking −0.25 per wrong SBA · pass mark not published" */
export function markingText(blueprint: Pick<BlueprintOut, 'negative_marking' | 'pass_mark_percent'>): string {
  const marking = blueprint.negative_marking.enabled
    ? `Negative marking −${blueprint.negative_marking.penalty} per wrong SBA`
    : 'No negative marking';
  const pass = blueprint.pass_mark_percent === null ? 'pass mark not published' : `pass mark ${blueprint.pass_mark_percent}%`;
  return `${marking} · ${pass}`;
}

/** How the per-system mix is chosen, in words. */
export function mixText(blueprint: Pick<BlueprintOut, 'mix_mode' | 'mix'>): string {
  if (blueprint.mix_mode === 'fixed') {
    return blueprint.mix.map((g) => `${g.label} ${Math.round(g.share * 100)}%`).join(' · ');
  }
  if (blueprint.mix_mode === 'weights') return 'Your approved past-paper weights (even until approved)';
  return 'Even across the systems this exam covers';
}

function bounded(raw: FormDataEntryValue | null, min: number, max: number, integer: boolean): number | null | false {
  const text = String(raw ?? '').trim();
  if (!text) return null;
  const value = Number(text);
  if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) return false;
  return value;
}

/** Owner override of time, negative marking, and pass mark; blank fields keep the default. */
export function parseBlueprintOverrideForm(form: FormData): Parsed<{ id: string; overrides: Record<string, unknown> }> {
  const id = String(form.get('blueprint_id') ?? '');
  if (!/^[a-z0-9_]{1,60}$/.test(id)) return { ok: false, error: 'Unknown blueprint.' };
  const minutes = bounded(form.get('duration_minutes'), 1, 600, true);
  if (minutes === false) return { ok: false, error: 'Duration must be 1–600 minutes.' };
  const penalty = bounded(form.get('penalty'), 0, 1, false);
  if (penalty === false) return { ok: false, error: 'Penalty must be between 0 and 1.' };
  const pass = bounded(form.get('pass_mark_percent'), 0, 100, false);
  if (pass === false) return { ok: false, error: 'Pass mark must be 0–100%.' };
  const overrides: Record<string, unknown> = {};
  if (minutes !== null) overrides.duration_minutes = minutes;
  if (penalty !== null) overrides.negative_marking = { enabled: penalty > 0, penalty };
  if (pass !== null) overrides.pass_mark_percent = pass;
  return { ok: true, value: { id, overrides } };
}
