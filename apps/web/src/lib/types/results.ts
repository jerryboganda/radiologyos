// Exam results review and grade disputes (ADR 0029): packages/assessment/exam_review.py,
// apps/api/app/api/disputes.py.
import type { LooseCitation } from './citation';

export interface ExamTiming {
  timed_items: number;
  total_seconds: number;
  mean_seconds: number | null;
  median_seconds: number | null;
  slowest: { question_id: string; seconds: number }[];
}

export interface CalibrationLevel {
  level: 1 | 2 | 3;
  label: string;
  /** The chance of being right this confidence stands for (0.40 / 0.65 / 0.90). */
  stated: number;
  count: number;
  /** Mean share of marks earned at this confidence; null with no rated items. */
  mean_score: number | null;
}

export interface ExamCalibration {
  rated: number;
  levels: CalibrationLevel[];
  /** Mean of (stated − earned): positive means overconfident. */
  bias: number | null;
  confidently_wrong: number;
  unsure_right: number;
}

export interface ExamReview {
  timing: ExamTiming;
  calibration: ExamCalibration;
}

export type DisputeStatus = 'open' | 'accepted' | 'rejected';

export interface DisputeIn {
  question_id: string;
  point_index: number;
  reason: string;
}

export interface DisputeOut {
  id: string;
  exam_id: string;
  question_id: string;
  point_index: number;
  reason: string;
  marks: number;
  awarded_before: number;
  awarded_after: number | null;
  status: DisputeStatus;
  resolution_note: string;
  created_at: string;
  resolved_at: string | null;
}

export interface DisputeQueueItem extends DisputeOut {
  user_id: string;
  stem: string;
  topic: string;
  point: string;
  justification: string;
  answer_text: string;
  model_answer: string;
  citations: LooseCitation[];
}

export interface DisputeResolveIn {
  action: 'accept' | 'reject';
  /** Accept: the new award (default: the point's full marks). */
  awarded?: number | null;
  note?: string;
}

export interface DisputeResolved {
  dispute: DisputeOut;
  exam_score: number | null;
  exam_percent: number | null;
}
