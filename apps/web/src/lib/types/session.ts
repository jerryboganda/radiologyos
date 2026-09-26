// Today session and progress-insights contracts (apps/api/app/schemas/study_sessions.py).
// Deliberately no pass-probability field anywhere: none is shown until validated.
import type { OptionExplanation, QuestionPublic, SchemePoint } from './assessment';
import type { LooseCitation } from './citation';
import type { CardCitation, CardOut } from './study';

export type StepKind = 'review' | 'learn' | 'test' | 'viva';
export type StepStatus = 'pending' | 'active' | 'done' | 'skipped';

export interface TopicRef {
  code: string;
  title: string;
}

export interface ReviewStepView {
  total: number;
  reviewed: number;
  cards: CardOut[];
}

export interface LearnChunk {
  chunk_id: string;
  heading: string;
  text: string;
  citation: CardCitation;
}

export interface LearnFigure {
  figure_id: string;
  caption: string;
  description: string;
  modality: string;
  image_path: string | null;
  citation: LooseCitation;
}

export interface LearnStepView {
  topic: TopicRef | null;
  chunks: LearnChunk[];
  figures: LearnFigure[];
}

export interface SbaFeedback {
  question_id: string;
  selected_option: number | null;
  key: number;
  correct: boolean;
  confidence: number | null;
  explanation: string;
  option_explanations: OptionExplanation[];
  citations: LooseCitation[];
}

export interface SbaBlockView {
  time_limit_minutes: number;
  total: number;
  answered: number;
  correct: number;
  /** Items re-testing an earlier wrong answer (weakness loop). */
  retests: number;
  questions: QuestionPublic[];
  results: SbaFeedback[];
}

export interface VivaResult {
  score: number | null;
  max_score: number | null;
  feedback: string | null;
  points: SchemePoint[] | null;
  model_answer: string | null;
  key_findings: string[] | null;
}

export interface VivaStepView {
  mode: 'graded' | 'self_review';
  topic: TopicRef | null;
  prompt: string | null;
  question: QuestionPublic | null;
  answer_text: string | null;
  status: 'unanswered' | 'pending' | 'graded' | 'failed' | 'self_review';
  citations: LooseCitation[];
  result: VivaResult | null;
  reference: { heading: string; text: string } | null;
}

export interface SessionStep {
  step_no: number;
  kind: StepKind;
  status: StepStatus;
  minutes: number;
  started_at: string | null;
  deadline_at: string | null;
  completed_at: string | null;
  review: ReviewStepView | null;
  learn: LearnStepView | null;
  test: SbaBlockView | null;
  viva: VivaStepView | null;
}

export interface SessionSummary {
  steps_done: number;
  steps_skipped: number;
  steps_total: number;
  reviews: number;
  sba_answered: number;
  sba_correct: number;
  viva_answered: boolean;
  minutes: number;
  weighted_coverage: number;
}

export interface StudySession {
  id: string;
  session_date: string;
  session_version: number;
  plan_version: number;
  status: 'active' | 'completed';
  summary: SessionSummary | null;
  created_at: string;
  completed_at: string | null;
  server_time: string;
  current_step: number | null;
  progress: { done: number; total: number };
  steps: SessionStep[];
  notice: string;
}

export interface StepAnswerIn {
  question_id?: string;
  selected_option?: number;
  confidence?: number | null;
  answer_text?: string;
}

export interface HeatmapCell {
  code: string;
  title: string;
  material: number;
  studied: number;
  coverage: number | null;
  accuracy: number | null;
  band: 'none' | 'weak' | 'learning' | 'mastered';
}

export interface HeatmapRow {
  code: string;
  title: string;
  mastery: number;
  band: string;
  coverage: number;
  weight: number;
  cells: HeatmapCell[];
}

export interface Projection {
  status: 'insufficient_history' | 'on_track' | 'behind' | 'done';
  days_remaining: number;
  target_days: number;
  goal: number;
  coverage: number;
  remaining_weighted: number;
  topics_remaining: number;
  sessions_in_window: number;
  coverage_per_day: number | null;
  minutes_per_day: number | null;
  projected_coverage: number | null;
  needed_minutes_per_day: number | null;
  needed_hours_per_day: number | null;
}

export interface CalibrationLevel {
  level: number;
  label: string;
  stated: number;
  answers: number;
  accuracy: number | null;
}

export interface Calibration {
  rated: number;
  bias: number | null;
  verdict: 'insufficient' | 'overconfident' | 'underconfident' | 'calibrated';
  levels: CalibrationLevel[];
  wrong: number;
  confident_wrong: number;
  confident_wrong_share: number | null;
  min_rated: number;
}

export interface Insights {
  heatmap: HeatmapRow[];
  projection: Projection;
  calibration: Calibration;
  weight_policy: string;
  notice: string;
}
