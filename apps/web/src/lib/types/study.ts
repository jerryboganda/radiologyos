// Planned study API (/v1/study/*). Shapes are the web's expectation; the UI
// degrades to "coming online" until the endpoints are deployed.
import type { Citation } from './citation';

export interface StudyProfile {
  exam_date: string | null;
  daily_minutes: number;
  exam_name?: string | null;
  timezone?: string | null;
}

export interface TodayBlock {
  id: string;
  kind: string;
  title: string;
  minutes: number;
  done?: boolean;
  href?: string | null;
  citations?: Citation[];
}

export interface TodayPlan {
  date: string;
  days_to_exam?: number | null;
  phase?: string | null;
  blocks: TodayBlock[];
}

export interface DueCard {
  id: string;
  front: string;
  back: string;
  topic?: string | null;
  citations: Citation[];
}

export interface DueCards {
  total: number;
  cards: DueCard[];
}

export type Rating = 'again' | 'hard' | 'good' | 'easy';
export const RATINGS: readonly Rating[] = ['again', 'hard', 'good', 'easy'];

export interface TopicProgress {
  code: string;
  name: string;
  weight?: number | null;
  mastery: number | null;
  coverage: number | null;
  due: number;
}

export interface DayActivity {
  date: string;
  minutes: number;
  reviews: number;
}

/** Deliberately has no pass-probability field: none is shown until validated. */
export interface StudyProgress {
  streak_days: number;
  reviews_7d: number;
  minutes_7d: number;
  retention_30d: number | null;
  topics: TopicProgress[];
  history: DayActivity[];
}
