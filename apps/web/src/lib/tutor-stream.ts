// Server-Sent Events for the tutor (POST /tutor/stream → /v1/tutor/ask/stream).
// Pure for node --test. Only progress streams: `status` events name a stage,
// then one `answer` (the JSON route's body) and `done`, or one `error`.
import { classifyFailure, failureText } from './api-state.ts';
import { isUuid } from './citations.ts';
import type { AskRequest, AskResponse } from './types/tutor.ts';

export type AskInput = { ok: true; body: AskRequest } | { ok: false; error: string };

/** Validate a tutor question from a form or JSON body (same rules as the API). */
export function validateAsk(question: unknown, threadId: unknown, allowWeb: unknown): AskInput {
  const text = typeof question === 'string' ? question.trim() : '';
  if (text.length < 3) return { ok: false, error: 'Ask a full question.' };
  if (text.length > 2000) return { ok: false, error: 'Keep questions under 2,000 characters.' };
  const thread = typeof threadId === 'string' && isUuid(threadId) ? threadId : null;
  return { ok: true, body: { question: text, thread_id: thread, allow_web: allowWeb === true || allowWeb === 'on' } };
}

export interface SseEvent {
  event: string;
  data: string;
}

export type TutorStage = 'retrieving' | 'answering' | 'web_research' | 'judging';

export const STAGE_LABEL: Record<TutorStage, string> = {
  retrieving: 'Searching your library…',
  answering: 'Writing a cited answer from your sources…',
  web_research: 'Researching authoritative radiology sites…',
  judging: 'Checking every sentence against what it cites…'
};

export function stageLabel(stage: string): string {
  return stage in STAGE_LABEL ? STAGE_LABEL[stage as TutorStage] : 'Working…';
}

/** Parse one SSE block (lines between blank lines); comments and empty data are ignored. */
export function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
  }
  return data.length ? { event, data: data.join('\n') } : null;
}

/** Incremental parser: feed decoded text chunks, get each complete event once. */
export function createSseParser(): (chunk: string) => SseEvent[] {
  let buffer = '';
  return (chunk) => {
    buffer += chunk;
    // Normalise CRLF/CR, but keep a trailing CR until its LF may arrive.
    const tail = buffer.endsWith('\r') ? '\r' : '';
    buffer = buffer.slice(0, buffer.length - tail.length).replace(/\r\n?/g, '\n');
    const events: SseEvent[] = [];
    let index = buffer.indexOf('\n\n');
    while (index !== -1) {
      const parsed = parseBlock(buffer.slice(0, index));
      if (parsed) events.push(parsed);
      buffer = buffer.slice(index + 2);
      index = buffer.indexOf('\n\n');
    }
    buffer += tail;
    return events;
  };
}

export type StreamOutcome =
  | { kind: 'answer'; answer: AskResponse }
  | { kind: 'error'; status: number; detail: string; message: string }
  | { kind: 'broken' };

function json(data: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(data);
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Apply one event; returns a final outcome for `error`/`done`, otherwise null. */
export function applyEvent(
  ev: SseEvent,
  state: { answer: AskResponse | null },
  onStage: (stage: string) => void
): StreamOutcome | null {
  const data = json(ev.data);
  if (ev.event === 'status' && typeof data?.stage === 'string') onStage(data.stage);
  if (ev.event === 'answer' && data && typeof data.thread_id === 'string') {
    state.answer = data as unknown as AskResponse;
  }
  if (ev.event === 'error') {
    const status = typeof data?.status === 'number' ? data.status : 500;
    const detail = typeof data?.detail === 'string' ? data.detail : 'The tutor failed.';
    return { kind: 'error', status, detail, message: failureText(classifyFailure(status, detail)) };
  }
  if (ev.event === 'done') return state.answer ? { kind: 'answer', answer: state.answer } : { kind: 'broken' };
  return null;
}

/**
 * Read the tutor SSE body to its end. `broken` means the stream itself failed
 * (network drop, proxy cut, no answer) and the caller should fall back to the
 * JSON route; `error` is an API answer (404/429/502/503) and must be shown.
 */
export async function readTutorStream(
  body: ReadableStream<Uint8Array>,
  onStage: (stage: string) => void
): Promise<StreamOutcome> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const push = createSseParser();
  const state: { answer: AskResponse | null } = { answer: null };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      const text = done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const ev of push(done ? `${text}\n\n` : text)) {
        const outcome = applyEvent(ev, state, onStage);
        if (outcome) {
          await reader.cancel().catch(() => undefined);
          return outcome;
        }
      }
      if (done) break;
    }
  } catch {
    // fall through: a dropped stream is `broken` unless the answer already arrived
  }
  return state.answer ? { kind: 'answer', answer: state.answer } : { kind: 'broken' };
}
