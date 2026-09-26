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
  /** Staged image cases only: the stage order (describe → next_step); never the answers. */
  stages?: string[];
}

export interface GenerateQuestionsIn {
  source_ids?: string[];
  topic?: string | null;
  type: GeneratableType;
  exam_target: ExamTarget;
  count?: number;
}

export interface RejectedItem {
  index: number;
  reasons: string[];
  /** Set when the item was a near-duplicate of one of your existing questions. */
  duplicate_of?: string | null;
  similarity?: number | null;
}

export interface GenerateQuestionsOut {
  created: QuestionPublic[];
  rejected: RejectedItem[];
  excerpt_count: number;
  duplicate_method?: 'embedding' | 'trigram';
}

export interface AttemptIn {
  selected_option?: number | null;
  answer_text?: string | null;
  /** Self-rated confidence on an SBA: 1 low, 2 medium, 3 high (calibration only). */
  confidence?: number | null;
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
  /** Item types to draw from; defaults to SBA only. */
  types?: GeneratableType[];
}

/** question_id → selected option index (0–4). */
export type Answers = Record<string, number>;
/** question_id → written answer for SEQ, image-case, and viva items. */
export type TextAnswers = Record<string, string>;

export interface AutosaveIn {
  revision: number;
  /** null clears an answer. */
  answers: Record<string, number | null>;
  text_answers?: Record<string, string | null>;
}

export interface AutosaveOut {
  exam_id: string;
  revision: number;
  deadline_at: string | null;
  answers: Answers;
  text_answers?: TextAnswers;
}

export type ItemStatus = 'graded' | 'pending' | 'failed';

export interface SbaResultItem {
  question_id: string;
  type?: 'sba';
  status?: ItemStatus;
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

export interface WrittenResultItem {
  question_id: string;
  type: 'seq' | 'image_case' | 'viva';
  status: ItemStatus;
  topic: string;
  answer_text: string;
  /** null while pending or after a grading failure. */
  score: number | null;
  max_score: number;
  points: SchemePoint[];
  feedback: string;
  model_answer: string;
  key_findings: string[];
  explanation: string;
  citations: LooseCitation[];
  error?: string;
  /** Staged image cases: marks per stage, from stage-tagged scheme points. */
  stage_scores?: { stage: string; score: number; max_score: number }[];
}

export type ExamResultItem = SbaResultItem | WrittenResultItem;

export interface TopicScore {
  topic: string;
  correct: number;
  total: number;
  answered: number;
  score?: number;
  max_score?: number;
}

export interface ExamResult {
  score: number;
  max_score: number;
  percent: number;
  answered: number;
  by_topic: TopicScore[];
  items: ExamResultItem[];
  timed_out?: boolean;
  pending?: number;
  failed?: number;
  grading?: 'pending' | 'complete';
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
  text_answers?: TextAnswers;
  questions: QuestionPublic[];
  result: ExamResult | null;
}

/** Draft review queue (GET /v1/questions/review): the owner's drafts in full. */
export interface ReviewItem {
  id: string;
  type: string;
  exam_tags: string[];
  topic: string;
  stem: string;
  options: OptionExplanation[];
  key: number | null;
  model_answer: string;
  marking_scheme: { point: string; marks: number; citations: LooseCitation[] }[];
  key_findings: string[];
  viva_turns: { question: string; expected_answer: string; citations: LooseCitation[] }[];
  explanation: string;
  citations: LooseCitation[];
  figure_image_path: string | null;
  status: string;
  status_reason: string | null;
  checker_reasons: string[];
  difficulty: number | null;
  created_at: string;
}

export type ReviewAction = 'approve' | 'reject' | 'edit';

export interface ReviewIn {
  action: ReviewAction;
  stem?: string;
  topic?: string;
  explanation?: string;
  options?: string[];
  key_index?: number;
  model_answer?: string;
}

export interface ReviewOut {
  action: string;
  status: string;
  item: ReviewItem;
}

export interface StatsRecomputeOut {
  computed: number;
  retired: { question_id: string; reason: string }[];
  stats: {
    question_id: string;
    attempts: number;
    correct: number;
    p_value: number | null;
    discrimination: number | null;
    discrimination_n: number;
    decision: string;
    reason: string | null;
  }[];
}
