// Planned assessment API (/v1/questions, /v1/exams).
import type { Citation } from './citation';

export interface Question {
  id: string;
  stem: string;
  options: string[];
  topic?: string | null;
  kind?: string | null;
  image_path?: string | null;
  citations: Citation[];
}

export interface AttemptResult {
  correct: boolean;
  correct_index: number;
  explanation: string;
  citations: Citation[];
}

export interface ExamSummary {
  id: string;
  title: string;
  kind: string;
  question_count: number;
  minutes: number;
  status: 'not_started' | 'in_progress' | 'submitted' | string;
  score?: number | null;
}
