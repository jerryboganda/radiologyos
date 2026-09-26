// Exam-taking helpers: server-clock timer math, autosave diffs, 409 handling,
// and the recent-exams cookie. Pure for node --test.
import type { Answers } from './types/assessment.ts';

export type Changes = Record<string, number | null>;

/** Server clock minus client clock, measured once when the exam view arrives. */
export function clockOffset(serverTime: string, clientNow: number): number {
  const server = Date.parse(serverTime);
  return Number.isFinite(server) ? server - clientNow : 0;
}

/** Milliseconds left on the server's clock; null for an untimed exam. Never negative. */
export function remainingMs(deadlineAt: string | null, offsetMs: number, clientNow: number): number | null {
  if (!deadlineAt) return null;
  const deadline = Date.parse(deadlineAt);
  if (!Number.isFinite(deadline)) return null;
  return Math.max(0, deadline - (clientNow + offsetMs));
}

/** "1:05:09" or "05:09". Rounds up so the clock reads 00:00 only when time is truly out. */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** What must be sent so the server matches `local`: changed options, null for cleared. */
export function pendingChanges(saved: Answers, local: Answers): Changes {
  const changes: Changes = {};
  for (const [id, option] of Object.entries(local)) {
    if (saved[id] !== option) changes[id] = option;
  }
  for (const id of Object.keys(saved)) {
    if (!(id in local)) changes[id] = null;
  }
  return changes;
}

/**
 * After a 409 stale revision: adopt the server's answers, then re-apply the
 * edits this tab made that were never saved (local differs from last saved).
 */
export function rebase(server: Answers, saved: Answers, local: Answers): Answers {
  const merged: Answers = { ...server };
  for (const [id, option] of Object.entries(pendingChanges(saved, local))) {
    if (option === null) delete merged[id];
    else merged[id] = option;
  }
  return merged;
}

export type SaveOutcome = 'saved' | 'stale' | 'closed' | 'retry' | 'error';

/** Map an autosave HTTP answer to what the exam screen should do next. */
export function saveOutcome(status: number, detail: string | null): SaveOutcome {
  if (status >= 200 && status < 300) return 'saved';
  if (status === 409) {
    if (detail === 'stale_revision') return 'stale';
    return 'closed'; // exam_submitted | exam_time_expired
  }
  if (status === 404) return 'stale'; // lost a revision race: reload shows the truth
  if (status === 0 || status === 429 || status >= 500) return 'retry';
  return 'error';
}

/** Exponential backoff for autosave retries, capped at 30 s. */
export function retryDelay(attempt: number): number {
  return Math.min(30_000, 1000 * 2 ** Math.max(0, attempt));
}

export function answeredCount(questionIds: string[], answers: Answers): number {
  return questionIds.filter((id) => typeof answers[id] === 'number').length;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const RECENT_EXAMS_COOKIE = 'radbrain_exams';
const MAX_RECENT = 8;

/** Parse the recent-exams cookie (comma-separated UUIDs); junk is dropped. */
export function parseRecentExams(value: string | undefined | null): string[] {
  return [...new Set((value ?? '').split(',').filter((id) => UUID.test(id)))].slice(0, MAX_RECENT);
}

/** Newest first, de-duplicated, capped. */
export function withRecentExam(ids: string[], examId: string): string[] {
  if (!UUID.test(examId)) return ids.slice(0, MAX_RECENT);
  return [examId, ...ids.filter((id) => id !== examId)].slice(0, MAX_RECENT);
}
