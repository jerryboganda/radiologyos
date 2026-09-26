// Assessment API contract (apps/api/app/assessment/contracts.py,
// packages/assessment/grading.py). Keys and explanations never appear on a
// question before it is answered; they arrive in an attempt or exam result.
import type { LooseCitation } from './citation';
import type { ExamTarget } from './study';

export type QuestionType = 'sba' | 'seq' | 'image_case' | 'viva' | 'rapid_recall';
/** The generator accepts every type except rapid_recall (graded by review). */
export type GeneratableType = Exclude<QuestionType, 'rapid_recall'>;

export const QUESTION_TYPES: { value: QuestionType; label: string }[] = [
  { value: 'sba', label: 'Single best answer' },
  { value: 'seq', label: 'Short essay (SEQ)' },
  { value: 'image_case', label: 'Image case' },
  { value: 'viva', label: 'Viva' },
  { value: 'rapid_recall', label: 'Rapid recall' }
];

export interface QuestionPublic {
  id: string;
  type: QuestionType | string;
  exam_tags: string[];
  topic: string;
  stem: string;
  options: string[];
  figure_id: string | null;
  figure_image_path: string | null;
  status: string;
  checked: boolean;
  difficulty: number | null;
  created_at: string;
}

export interface GenerateQuestionsIn {
  source_ids?: string[];
  topic?: string | null;
  type: GeneratableType;
  exam_target: ExamTarget;
  count?: number;
}

export interface GenerateQuestionsOut {
  created: QuestionPublic[];
  rejected: { index: number; reasons: string[] }[];
  excerpt_count: number;
}

export interface AttemptIn {
  selected_option?: number | null;
  answer_text?: string | null;
}

export interface OptionExplanation {
  text: string;
  explanation: string;
  citations: LooseCitation[];
}

export interface SchemePoint {
  point: string;
  marks: number;
  awarded: number;
  status: string;
  justification: string;
  citations: LooseCitation[];
}

export interface AttemptOut {
  attempt_id: string | null;
  question_id: string;
  type: string;
  score: number;
  max_score: number;
  correct?: boolean | null;
  key?: number | null;
  explanation: string;
  option_explanations?: OptionExplanation[];
  points?: SchemePoint[];
  feedback?: string;
  model_answer?: string;
  key_findings?: string[];
  citations: LooseCitation[];
}

export interface ExamCreate {
  mode: 'practice' | 'exam';
  exam_target?: ExamTarget | null;
  topic?: string | null;
  count: number;
  time_limit_minutes?: number | null;
}

/** question_id → selected option index (0–4). */
export type Answers = Record<string, number>;

export interface AutosaveIn {
  revision: number;
  /** null clears an answer. */
  answers: Record<string, number | null>;
}

export interface AutosaveOut {
  exam_id: string;
  revision: number;
  deadline_at: string | null;
  answers: Answers;
}

export interface ExamResultItem {
  question_id: string;
  topic: string;
  selected_option: number | null;
  key: number;
  correct: boolean;
  score: number;
  max_score: number;
  explanation: string;
  option_explanations: OptionExplanation[];
  citations: LooseCitation[];
}

export interface TopicScore {
  topic: string;
  correct: number;
  total: number;
  answered: number;
}

export interface ExamResult {
  score: number;
  max_score: number;
  percent: number;
  answered: number;
  by_topic: TopicScore[];
  items: ExamResultItem[];
  timed_out?: boolean;
}

export type ExamStatus = 'active' | 'expired' | 'submitted';

export interface ExamView {
  id: string;
  mode: string;
  status: ExamStatus | string;
  config: Record<string, unknown>;
  started_at: string;
  deadline_at: string | null;
  submitted_at: string | null;
  server_time: string;
  revision: number;
  answers: Answers;
  questions: QuestionPublic[];
  result: ExamResult | null;
}
