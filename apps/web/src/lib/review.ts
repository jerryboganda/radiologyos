// Draft review form parsing and reason labels. Pure for node --test.
import type { ReviewIn } from './types/assessment.ts';
import type { Parsed } from './questions.ts';

const ACTIONS = ['approve', 'reject', 'edit'] as const;
const MAX = 8000;

const REASONS: Record<string, string> = {
  checker_error: 'The independent checker could not run.',
  checker_failed: 'The independent checker did not pass this item.',
  citations_stale: 'A cited source page or figure no longer exists; it cannot be approved.',
  not_a_draft: 'Only drafts can be approved or edited.',
  already_retired: 'This question is already retired.',
  sba_options_not_distinct: 'Options must be five distinct, non-empty answers.',
  sba_key_out_of_range: 'Choose which option is the key.',
  sba_key_repeated_in_stem: 'The key must not be repeated in the stem.',
  sba_all_or_none_of_the_above: 'Avoid "all/none of the above".',
  sba_stem_too_long: 'Keep the stem to 120 words or fewer.',
  stem_missing: 'The stem cannot be empty.',
  model_answer_missing: 'Written items need a model answer.'
};

/** Human text for API review refusals (comma-joined codes) and checker reasons. */
export function reviewMessage(detail: string): string {
  const parts = detail.split(',').map((code) => REASONS[code.trim()] ?? code.trim());
  return parts.filter(Boolean).join(' ');
}

function field(form: FormData, name: string, min = 1): string | null | undefined {
  if (!form.has(name)) return undefined;
  const value = String(form.get(name) ?? '').trim();
  if (value.length < min || value.length > MAX) return null;
  return value;
}

/** Only fields that differ from the stored item are sent, so an edit is minimal. */
export function parseReviewForm(form: FormData, original: { stem: string; topic: string; explanation: string; options: string[]; key: number | null; model_answer: string }): Parsed<ReviewIn> {
  const action = String(form.get('action') ?? '');
  if (!(ACTIONS as readonly string[]).includes(action)) return { ok: false, error: 'Unknown review action.' };
  if (action !== 'edit') return { ok: true, value: { action: action as ReviewIn['action'] } };
  const body: ReviewIn = { action: 'edit' };
  for (const name of ['stem', 'topic', 'model_answer'] as const) {
    const value = field(form, name);
    if (value === null) return { ok: false, error: `The ${name.replace('_', ' ')} cannot be empty.` };
    if (value !== undefined && value !== original[name]) body[name] = value;
  }
  const explanation = field(form, 'explanation', 0);
  if (explanation === null) return { ok: false, error: 'The explanation is too long.' };
  if (explanation !== undefined && explanation !== original.explanation) body.explanation = explanation;
  if (form.has('option_0')) {
    const options = [0, 1, 2, 3, 4].map((i) => String(form.get(`option_${i}`) ?? '').trim());
    if (options.some((o) => !o || o.length > MAX)) return { ok: false, error: 'Every option needs text.' };
    if (options.some((o, i) => o !== original.options[i])) body.options = options;
    const key = Number(form.get('key_index'));
    if (!Number.isInteger(key) || key < 0 || key > 4) return { ok: false, error: 'Choose which option is the key.' };
    if (key !== original.key) body.key_index = key;
  }
  if (Object.keys(body).length === 1) return { ok: false, error: 'Nothing was changed.' };
  return { ok: true, value: body };
}
