// Viva and staged image-case contract (apps/api/app/assessment/viva_contracts.py).
// A turn's expected answer arrives only once that turn is graded or the session ends.
import type { LooseCitation } from './citation';

export type VivaKind = 'viva' | 'image_case';
export type VivaStyle = 'practice' | 'fcps2_toacs' | 'frcr_2b_oral';
export type VivaStatus = 'preparing' | 'active' | 'finished' | 'failed';
export type Verdict = 'good' | 'partial' | 'miss';

export const VIVA_STYLES: { value: VivaStyle; label: string }[] = [
  { value: 'practice', label: 'Practice viva' },
  { value: 'fcps2_toacs', label: 'FCPS-II TOACS / viva' },
  { value: 'frcr_2b_oral', label: 'FRCR 2B oral' }
];

export interface VivaCreateIn {
  kind: VivaKind;
  style: VivaStyle;
  topic?: string | null;
  figure_id?: string | null;
  question_id?: string | null;
  max_turns?: number | null;
  time_limit_minutes?: number | null;
}

export interface ExpectedPoint {
  point: string;
  marks?: number;
  stage?: string;
  citations: LooseCitation[];
}

export interface GradedPoint {
  point: string;
  status: 'matched' | 'partial' | 'missed' | string;
  justification: string;
  marks?: number;
  awarded?: number;
  citations: LooseCitation[];
}

export interface TeachingPoint {
  text: string;
  citations: LooseCitation[];
  turn_no?: number;
  verdict?: Verdict | string;
}

export interface TurnEvaluation {
  verdict: Verdict | string;
  scores: Record<string, number>;
  points: GradedPoint[];
  feedback: string;
  teaching_point: TeachingPoint | null;
  unsafe?: boolean;
  move?: 'escalate' | 'probe';
  score?: number;
  max_score?: number;
  model_answer?: string;
}

export interface VivaTurn {
  turn_no: number;
  stage: string | null;
  stage_label: string | null;
  level: number;
  move: 'open' | 'escalate' | 'probe' | 'stage' | string;
  prompt: string;
  hint: string;
  status: 'asked' | 'answered' | 'graded' | 'skipped' | string;
  answer_text: string | null;
  answered_at: string | null;
  expected: ExpectedPoint[];
  evaluation: TurnEvaluation | null;
}

export interface Competency {
  key: string;
  label: string;
  percent: number | null;
  turns: number;
}

export interface StageScore {
  stage: string;
  score: number;
  max_score: number;
}

export interface VivaDebrief {
  stop_reason: string;
  turns_answered: number;
  overall_percent: number;
  level_reached: number;
  competencies: Competency[];
  stages: StageScore[];
  teaching_points: TeachingPoint[];
  weak_turns: number[];
  weak_areas?: number;
}

export interface VivaSession {
  id: string;
  kind: VivaKind | string;
  style: VivaStyle | string;
  topic: string;
  status: VivaStatus | string;
  work: 'none' | 'pending' | 'running' | string;
  error_code: string | null;
  scenario: string;
  scenario_citations: LooseCitation[];
  figure_id: string | null;
  figure_image_path: string | null;
  question_id: string | null;
  level: number;
  miss_streak: number;
  max_turns: number;
  started_at: string;
  deadline_at: string | null;
  finished_at: string | null;
  server_time: string;
  stop_reason: string | null;
  current_turn: number | null;
  turns: VivaTurn[];
  debrief: VivaDebrief | null;
}

export interface VivaSummary {
  id: string;
  kind: VivaKind | string;
  style: VivaStyle | string;
  topic: string;
  status: VivaStatus | string;
  started_at: string;
  finished_at: string | null;
  stop_reason: string | null;
  overall_percent: number | null;
}
