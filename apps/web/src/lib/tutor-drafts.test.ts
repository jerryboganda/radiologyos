import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applyDraft, emptyDrafts, hasDrafts, MAX_DRAFT_CHARS } from './tutor-drafts.ts';
import { imageProblem, MAX_IMAGE_BYTES, uploadedId } from './tutor-image.ts';
import { parseFocus, readTutorStream, stageLabel, validateAsk } from './tutor-stream.ts';

const IMAGE = '0b6f8c1e-8c55-4c3e-9d8e-2f6a5b1c7d90';
const SOURCE = '4f1f2d8a-6e0b-4a57-8c6d-2b8e5f3a9c10';

function frames(...parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    }
  });
}

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

test('draft operations append, replace, shrink, and ignore junk', () => {
  let drafts = emptyDrafts();
  assert.equal(hasDrafts(drafts), false);
  drafts = applyDraft(drafts, { phase: 'sources', segment: 0, text: 'PAP' });
  drafts = applyDraft(drafts, { phase: 'sources', segment: 0, append: ' shows' });
  drafts = applyDraft(drafts, { phase: 'sources', segment: 2, append: 'x' });
  assert.deepEqual(drafts.sources, ['PAP shows', '', 'x']);
  drafts = applyDraft(drafts, { phase: 'sources', count: 1 });
  assert.deepEqual(drafts.sources, ['PAP shows']);
  drafts = applyDraft(drafts, { phase: 'web', segment: 0, text: 'From the web' });
  assert.deepEqual(drafts.web, ['From the web']);
  for (const junk of [null, {}, { phase: 'other', segment: 0, text: 'x' }, { phase: 'web', segment: -1, text: 'x' },
    { phase: 'web', segment: 1.5, text: 'x' }, { phase: 'web', segment: 999, text: 'x' }, { phase: 'web', segment: 0 }]) {
    assert.equal(applyDraft(drafts, junk as Record<string, unknown> | null), drafts);
  }
  assert.equal(hasDrafts(drafts), true);
  const long = applyDraft(emptyDrafts(), { phase: 'web', segment: 0, text: 'y'.repeat(MAX_DRAFT_CHARS + 50) });
  assert.equal(long.web[0]?.length, MAX_DRAFT_CHARS);
});

test('the stream hands draft events over and still ends with the verified answer', async () => {
  const ops: Record<string, unknown>[] = [];
  const stages: string[] = [];
  const answer = { thread_id: 't1', message_id: 'm1', grounding: 'sources', segments: [] };
  const outcome = await readTutorStream(
    frames(
      sse('status', { stage: 'reading_image' }),
      sse('draft', { phase: 'sources', segment: 0, text: 'Dra' }),
      'event: draft\ndata: {"phase":"sources","segment":0,',
      '"append":"ft"}\n\n',
      sse('status', { stage: 'judging' }),
      sse('answer', answer),
      sse('done', {})
    ),
    (stage) => stages.push(stage),
    (op) => ops.push(op)
  );
  assert.equal(outcome.kind, 'answer');
  assert.deepEqual(stages, ['reading_image', 'judging']);
  const drafts = ops.reduce(applyDraft, emptyDrafts());
  assert.deepEqual(drafts.sources, ['Draft']);
});

test('drafts are optional for the stream reader', async () => {
  const outcome = await readTutorStream(frames(sse('draft', { phase: 'sources', segment: 0, text: 'x' })), () => undefined);
  assert.equal(outcome.kind, 'broken');
});

test('new stages have labels', () => {
  assert.equal(stageLabel('reading_image'), 'Reading your image…');
  assert.match(stageLabel('remembering'), /Summarising/);
});

test('validateAsk carries an image and a Reader page when valid', () => {
  const ok = validateAsk('What is this?', '', 'on', { image_id: IMAGE, focus_source: SOURCE, focus_page: '7' });
  assert.deepEqual(ok, {
    ok: true,
    body: { question: 'What is this?', thread_id: null, allow_web: true, image_id: IMAGE, focus: { source_id: SOURCE, page_no: 7 } }
  });
  const bad = validateAsk('What is this?', '', false, { image_id: '../x', focus_source: SOURCE, focus_page: '0' });
  assert.ok(bad.ok && !('image_id' in bad.body) && !('focus' in bad.body));
});

test('image checks refuse DICOM, other types, empty and oversized files', () => {
  assert.equal(imageProblem('image/png', 10, 'spotter.png'), null);
  assert.equal(imageProblem('image/webp', MAX_IMAGE_BYTES), null);
  assert.match(imageProblem('application/dicom', 10) ?? '', /DICOM/);
  assert.match(imageProblem('', 10, 'IM0001.DCM') ?? '', /DICOM/);
  assert.match(imageProblem('image/gif', 10) ?? '', /PNG, JPEG, or WebP/);
  assert.match(imageProblem('image/png', 0) ?? '', /empty/);
  assert.match(imageProblem('image/jpeg', MAX_IMAGE_BYTES + 1) ?? '', /20 MB/);
  assert.equal(uploadedId({ image_id: IMAGE }), IMAGE);
  assert.equal(uploadedId({ image_id: '../../x' }), null);
  assert.equal(uploadedId(null), null);
});

test('parseFocus needs a uuid and a page number in range', () => {
  assert.deepEqual(parseFocus(SOURCE, 3), { source_id: SOURCE, page_no: 3 });
  assert.equal(parseFocus('nope', 3), null);
  assert.equal(parseFocus(SOURCE, '3e2'), null);
  assert.equal(parseFocus(SOURCE, 100_001), null);
  assert.equal(parseFocus(SOURCE, null), null);
});
