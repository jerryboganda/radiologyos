// Study API contract (apps/api/app/schemas/study.py). The exam date comes first:
// /v1/study/today and /v1/study/progress answer 409 until a profile exists.
// Deliberately no pass-probability field anywhere: none is shown until validated.
import type { BlockRef } from './citation';

export type ExamTarget = 'fcps2_theory' | 'fcps2_toacs' | 'imm' | 'frcr';

export const EXAM_TARGETS: { value: ExamTarget; label: string }[] = [
  { value: 'fcps2_theory', label: 'FCPS-II theory' },
  { value: 'fcps2_toacs', label: 'FCPS-II TOACS' },
  { value: 'imm', label: 'IMM' },
  { value: 'frcr', label: 'FRCR' }
];

export function isExamTarget(value: unknown): value is ExamTarget {
  return EXAM_TARGETS.some((t) => t.value === value);
}

export interface ReminderSettings {
  enabled: boolean;
  time: string | null;
}

export interface ProfileIn {
  exam_date: string;
  exam_targets: ExamTarget[];
  daily_minutes: number;
  weekday_minutes?: number | null;
  weekend_minutes?: number | null;
  timezone: string;
  reminder?: ReminderSettings;
}

export interface ProfileOut {
  exam_date: string;
  exam_targets: string[];
  daily_minutes: number;
  weekday_minutes: number | null;
  weekend_minutes: number | null;
  timezone: string;
  reminder: ReminderSettings;
  days_remaining: number;
  phase: string;
}

export interface PlanTopic {
  code: string;
  title: string;
  minutes: number;
  slots: number;
}

export interface PlanBlock {
  kind: 'review' | 'learn' | 'test' | 'viva';
  minutes: number;
  due_cards?: number | null;
  target_cards?: number | null;
  new_cards?: number | null;
  topics?: PlanTopic[] | string[] | null;
  questions?: number | null;
  from_today_topics?: number | null;
  interleaved_weak?: number | null;
  weak_topics?: string[] | null;
  mock_paper_suggested?: boolean | null;
  format?: string | null;
  image_prompts?: number | null;
}

export interface PriorityItem {
  code: string;
  title: string;
  priority: number;
  mastery: number;
  band: string;
}

export interface PlanOut {
  plan_version: number;
  plan_date: string;
  exam_date: string;
  days_remaining: number;
  phase: string;
  rule: string;
  minutes: number;
  retention: number;
  exam_targets: string[];
  weight_policy: string;
  blocks: PlanBlock[];
  priorities: PriorityItem[];
  generated_at: string;
}

export interface CardCitation {
  source_id: string;
  source_title: string;
  chunk_id?: string | null;
  page_from: number;
  page_to: number;
  block_refs?: BlockRef[];
}

export interface CardOut {
  id: string;
  curriculum_code: string;
  topic: string;
  front: string;
  back: string;
  origin: string;
  citation: CardCitation;
  state: string;
  stability: number;
  difficulty: number;
  due_at: string;
  last_review_at: string | null;
  reps: number;
  lapses: number;
}

/** FSRS rating: 1 Again, 2 Hard, 3 Good, 4 Easy. */
export type Rating = 1 | 2 | 3 | 4;
export const RATINGS: readonly Rating[] = [1, 2, 3, 4];

export function parseRating(value: unknown): Rating | null {
  const n = Number(value);
  return (RATINGS as readonly number[]).includes(n) ? (n as Rating) : null;
}

export interface ReviewOut {
  card: CardOut;
  scheduled_days: number;
  retention: number;
}

export interface GenerateCardsIn {
  source_id?: string | null;
  chunk_ids?: string[];
  max_cards?: number;
}

export interface GenerateCardsOut {
  created: CardOut[];
  rejected: number;
  chunks_used: number;
}

export interface TopicProgress {
  code: string;
  title: string;
  mastery: number;
  band: string;
  accuracy: number;
  retrievability: number;
  coverage: number;
  cards: number;
  lapses: number;
  priority: number;
}

export interface ProgressOut {
  exam_date: string;
  days_remaining: number;
  phase: string;
  retention: number;
  cards: number;
  due_now: number;
  new_cards: number;
  reviews_total: number;
  reviews_today: number;
  topics: TopicProgress[];
  notice: string;
}
