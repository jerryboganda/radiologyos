// Study helpers: onboarding detection, profile form parsing, plan block copy.
// Pure for node --test.
import { isKind, type ApiResult } from './api-state.ts';
import { isExamTarget, type ExamTarget, type PlanBlock, type ProfileIn, type ProfileOut } from './types/study.ts';

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** The exam date comes first: no profile (404) or a 409 from a plan route means onboarding. */
export function needsOnboarding(profile: ApiResult<unknown>, plan?: ApiResult<unknown>): boolean {
  return isKind(profile, 'not_found') || (plan !== undefined && isKind(plan, 'conflict'));
}

export type ProfileParse = { ok: true; profile: ProfileIn } | { ok: false; error: string };

/**
 * Build a full PUT body from the onboarding/settings form. PUT replaces the
 * profile, so fields the form does not edit are carried over from `existing`.
 */
export function parseProfileForm(form: FormData, existing: ProfileOut | null = null): ProfileParse {
  const examDate = String(form.get('exam_date') ?? '');
  if (!ISO_DATE.test(examDate)) return { ok: false, error: 'Choose your exam date.' };
  const minutes = Number(form.get('daily_minutes') ?? 90);
  if (!Number.isInteger(minutes) || minutes < 15 || minutes > 600) {
    return { ok: false, error: 'Daily study time must be between 15 and 600 minutes.' };
  }
  const targets = [...new Set(form.getAll('exam_targets').map(String))].filter(isExamTarget) as ExamTarget[];
  if (targets.length === 0) return { ok: false, error: 'Choose at least one exam.' };
  const timezone = String(form.get('timezone') ?? '').trim().slice(0, 64) || existing?.timezone || 'UTC';
  const profile: ProfileIn = { exam_date: examDate, exam_targets: targets, daily_minutes: minutes, timezone };
  if (existing) {
    profile.weekday_minutes = existing.weekday_minutes;
    profile.weekend_minutes = existing.weekend_minutes;
    profile.reminder = existing.reminder;
  }
  return { ok: true, profile };
}

export interface BlockView {
  title: string;
  details: string[];
  href: string;
}

function topicNames(topics: PlanBlock['topics']): string[] {
  return (topics ?? []).map((t) => (typeof t === 'string' ? t : t.title)).filter(Boolean);
}

function count(n: number | null | undefined, label: string): string | null {
  return n ? `${n} ${label}${n === 1 ? '' : 's'}` : null;
}

/** Human copy and a destination for one plan block. */
export function blockView(block: PlanBlock): BlockView {
  const topics = topicNames(block.topics);
  const weak = block.weak_topics ?? [];
  const extra = (items: (string | null)[]) => items.filter((d): d is string => !!d);
  switch (block.kind) {
    case 'review':
      return { title: 'Review due cards', href: '#review', details: extra([count(block.due_cards, 'due card'), count(block.target_cards, 'target card')]) };
    case 'learn':
      return {
        title: topics.length ? `Learn: ${topics.slice(0, 3).join(', ')}` : 'Learn new material',
        href: '/knowledge',
        details: extra([count(block.new_cards, 'new card'), topics.length > 3 ? `+${topics.length - 3} more topics` : null])
      };
    case 'test':
      return {
        title: block.mock_paper_suggested ? 'Timed mock paper' : 'Practice questions',
        href: block.mock_paper_suggested ? '/exams' : '/questions',
        details: extra([count(block.questions, 'question'), weak.length ? `Weak: ${weak.slice(0, 3).join(', ')}` : null])
      };
    case 'viva':
      return {
        title: 'Viva practice',
        href: '/questions?type=viva',
        details: extra([block.format ?? null, count(block.image_prompts, 'image prompt')])
      };
    default:
      return { title: String((block as { kind: string }).kind), href: '/', details: [] };
  }
}
