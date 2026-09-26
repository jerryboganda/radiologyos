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
  /** 'past_paper_approved' (owner-approved weights) or 'equal_unvalidated'. */
  weight_policy: string;
  weight_targets?: string[];
  blocks: PlanBlock[];
  priorities: PriorityItem[];
  generated_at: string;
}

export interface CardCitation {
  /** chunk (default), claim (cloze cards), or figure (image cards). */
  kind?: string | null;
  source_id: string;
  source_title: string;
  chunk_id?: string | null;
  claim_id?: string | null;
  figure_id?: string | null;
  page_from: number;
  page_to: number;
  block_refs?: BlockRef[];
  /** Figure bounding box (image cards). */
  bbox?: number[];
}

/** basic Q/A, cloze (a claim with its key term blanked), or image (a figure). */
export type CardType = 'basic' | 'cloze' | 'image';

export interface CardOut {
  id: string;
  curriculum_code: string;
  topic: string;
  front: string;
  back: string;
  origin: string;
  card_type?: CardType;
  claim_id?: string | null;
  figure_id?: string | null;
  /** Image cards: the figure through the signed media route. */
  figure_image_path?: string | null;
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

/** Cloze cards from verified claims, or image cards from described figures (ADR 0029). */
export interface KnowledgeCardsIn {
  kind: 'cloze' | 'image';
  source_id?: string | null;
  topic?: string | null;
  max_cards?: number;
}

export interface KnowledgeCardsOut {
  kind: 'cloze' | 'image';
  created: CardOut[];
  skipped: number;
  considered: number;
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
  questions?: number;
  attempts?: number;
  weight?: number;
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
  weight_policy: string;
  weight_targets: string[];
  topics: TopicProgress[];
  notice: string;
}

export interface BaselineSystemResult {
  code: string;
  title: string;
  questions: number;
  correct: number;
  accuracy: number;
}

/** A short timed SBA baseline across systems; taken on /exams/{exam_id}. */
export interface BaselineOut {
  id: string;
  exam_id: string;
  status: 'open' | 'expired' | 'submitted';
  question_count: number;
  systems: string[];
  started_at: string;
  deadline_at: string | null;
  submitted_at: string | null;
  results: BaselineSystemResult[];
}

export interface WeeklyReportOut {
  report_version: number;
  week_start: string;
  week_end: string;
  minutes_studied: number;
  planned_minutes: number;
  daily_minutes: number[];
  active_days: number;
  reviews: number;
  questions: number;
  question_accuracy: number | null;
  retention: { achieved: number | null; target: number; eligible_reviews: number; met: boolean | null };
  weakest: { code: string; title: string; mastery: number; band: string }[];
  focus: { code: string; title: string; reason: string }[];
  notes: string[];
  days_remaining: number;
  phase: string;
  weight_policy: string;
  generated_at: string;
}
