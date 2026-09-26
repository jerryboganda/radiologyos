import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createSseParser, parseBlock, readTutorStream, stageLabel, validateAsk } from './tutor-stream.ts';

const ANSWER = { thread_id: 't1', message_id: 'm1', grounding: 'sources', segments: [] };

function frames(...parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    }
  });
}

function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

test('parseBlock reads event and data, ignoring comments', () => {
  assert.deepEqual(parseBlock('event: status\ndata: {"stage":"answering"}'), {
    event: 'status',
    data: '{"stage":"answering"}'
  });
  assert.deepEqual(parseBlock('data: a\ndata: b'), { event: 'message', data: 'a\nb' });
  assert.equal(parseBlock(': keep-alive'), null);
});

test('the parser reassembles events split across chunks and CRLF boundaries', () => {
  const push = createSseParser();
  assert.deepEqual(push('event: sta'), []);
  assert.deepEqual(push('tus\r\ndata: {"stage":"retrieving"}\r'), []);
  const events = push('\n\r\n: keep-alive\n\nevent: done\ndata: {}\n\n');
  assert.deepEqual(
    events.map((e) => e.event),
    ['status', 'done']
  );
  assert.equal(events[0]?.data, '{"stage":"retrieving"}');
});

test('readTutorStream reports stages then returns the answer', async () => {
  const stages: string[] = [];
  const body = frames(
    sse('status', { stage: 'retrieving' }),
    ': keep-alive\n\n',
    sse('status', { stage: 'answering' }) + sse('status', { stage: 'judging' }),
    sse('answer', ANSWER).slice(0, 20),
    sse('answer', ANSWER).slice(20) + sse('done', { thread_id: 't1', message_id: 'm1' })
  );
  const outcome = await readTutorStream(body, (s) => stages.push(s));
  assert.deepEqual(stages, ['retrieving', 'answering', 'judging']);
  assert.equal(outcome.kind, 'answer');
  assert.equal(outcome.kind === 'answer' && outcome.answer.thread_id, 't1');
});

test('an error event is final and carries a friendly message', async () => {
  const body = frames(sse('status', { stage: 'retrieving' }), sse('error', { status: 429, detail: 'usage window' }));
  const outcome = await readTutorStream(body, () => undefined);
  assert.equal(outcome.kind, 'error');
  if (outcome.kind === 'error') {
    assert.equal(outcome.status, 429);
    assert.match(outcome.message, /usage window/i);
  }
});

test('a stream that ends without an answer is broken (fall back to JSON)', async () => {
  assert.deepEqual(await readTutorStream(frames(sse('status', { stage: 'answering' })), () => undefined), {
    kind: 'broken'
  });
  assert.deepEqual(await readTutorStream(frames('garbage without blank line'), () => undefined), { kind: 'broken' });
});

test('an answer without a trailing done still counts', async () => {
  const outcome = await readTutorStream(frames(sse('answer', ANSWER).trimEnd()), () => undefined);
  assert.equal(outcome.kind, 'answer');
});

test('validateAsk mirrors the API limits and drops bad thread ids', () => {
  const thread = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';
  assert.deepEqual(validateAsk('  What is PAP?  ', thread, 'on'), {
    ok: true,
    body: { question: 'What is PAP?', thread_id: thread, allow_web: true }
  });
  assert.deepEqual(validateAsk('Why?', 'not-a-uuid', false), {
    ok: true,
    body: { question: 'Why?', thread_id: null, allow_web: false }
  });
  assert.equal(validateAsk('x', null, true).ok, false);
  assert.equal(validateAsk('x'.repeat(2001), null, true).ok, false);
  assert.equal(validateAsk(42, null, true).ok, false);
});

test('stage labels are human and unknown stages are generic', () => {
  assert.match(stageLabel('judging'), /Checking/);
  assert.equal(stageLabel('mystery'), 'Working…');
});
