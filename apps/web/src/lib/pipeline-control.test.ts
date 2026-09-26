import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  awaitingParts,
  awaitingText,
  awaitingTotal,
  clockTime,
  confirmsQuota,
  isPipelineStatus,
  pipelineProgress,
  pipelineSummary,
  providerName
} from './pipeline-control.ts';
import type { PipelineStatus } from './types/admin.ts';

function status(overrides: Partial<PipelineStatus> = {}): PipelineStatus {
  return {
    paused: null,
    resume_at: null,
    provider: null,
    pages: { done: 120, pending: 30, failed: 2 },
    jobs: { succeeded: 3, running: 1 },
    knowledge_units: { succeeded: 40, failed: 1, skipped: 5 },
    awaiting_owner: {},
    ...overrides
  };
}

// 2026-09-26T14:05:00Z
const RESUME = Date.UTC(2026, 8, 26, 14, 5) / 1000;

test('isPipelineStatus accepts the API shape and rejects malformed bodies', () => {
  assert.equal(isPipelineStatus(status()), true);
  assert.equal(isPipelineStatus(status({ paused: 'quota', resume_at: RESUME, provider: 'chatgpt' })), true);
  assert.equal(isPipelineStatus(null), false);
  assert.equal(isPipelineStatus({ ...status(), paused: 1 }), false);
  assert.equal(isPipelineStatus({ ...status(), resume_at: 'soon' }), false);
  assert.equal(isPipelineStatus({ ...status(), resume_at: Number.NaN }), false);
  assert.equal(isPipelineStatus({ ...status(), provider: undefined }), false);
  assert.equal(isPipelineStatus({ ...status(), pages: { done: '3' } }), false);
  assert.equal(isPipelineStatus({ ...status(), jobs: [1, 2] }), false);
  assert.equal(isPipelineStatus({ ...status(), knowledge_units: { failed: -1 } }), false);
  const missing: Record<string, unknown> = { ...status() };
  delete missing.awaiting_owner;
  assert.equal(isPipelineStatus(missing), false);
});

test('summary: paused by the owner', () => {
  assert.deepEqual(pipelineSummary(status({ paused: 'manual' })), { text: 'Paused by you', tone: 'warn', paused: true });
});

test('summary: quota pause names the provider and the resume time', () => {
  const summary = pipelineSummary(status({ paused: 'quota', provider: 'chatgpt', resume_at: RESUME }), 'UTC');
  assert.equal(summary.text, 'Paused — ChatGPT quota reached, resumes about 14:05');
  assert.equal(summary.paused, true);
  assert.equal(pipelineSummary(status({ paused: 'quota', provider: 'chatgpt', resume_at: RESUME }), 'Asia/Karachi').text.endsWith('19:05'), true);
  assert.equal(pipelineSummary(status({ paused: 'quota' })).text, 'Paused — model quota reached');
  assert.equal(pipelineSummary(status({ paused: 'maintenance' })).text, 'Paused');
});

test('summary: running while work remains, idle otherwise', () => {
  assert.deepEqual(pipelineSummary(status()), { text: 'Running', tone: 'ok', paused: false });
  const idle = status({ pages: { done: 10 }, jobs: { succeeded: 2 } });
  assert.deepEqual(pipelineSummary(idle), { text: 'Idle — nothing waiting', tone: 'idle', paused: false });
});

test('providerName and clockTime', () => {
  assert.equal(providerName('chatgpt'), 'ChatGPT');
  assert.equal(providerName('mistral'), 'Mistral');
  assert.equal(providerName(null), 'model');
  assert.equal(clockTime(RESUME, 'UTC'), '14:05');
});

test('progress counts pages, books, and knowledge units', () => {
  assert.deepEqual(pipelineProgress(status({ jobs: { queued: 2, running: 1, failed: 1, succeeded: 4 } })), {
    pagesRead: 120,
    pagesTotal: 152,
    pagesFailed: 2,
    booksActive: 3,
    booksFailed: 1,
    unitsDone: 40,
    unitsFailed: 1
  });
  assert.equal(pipelineProgress(status({ pages: {}, jobs: {}, knowledge_units: {} })).pagesTotal, 0);
});

test('awaiting approval: total and plain-English breakdown', () => {
  const waiting = status({ awaiting_owner: { knowledge_extract: 1, image_case: 3, page_parse: 12, tagger: 2, empty: 0 } });
  assert.equal(awaitingTotal(waiting), 18);
  assert.deepEqual(
    awaitingParts(waiting).map((p) => p.agent),
    ['page_parse', 'image_case', 'knowledge_extract', 'tagger']
  );
  assert.equal(awaitingText(waiting), '12 pages, 3 figures, 1 note, 2 other items');
  assert.equal(awaitingText(status()), '');
  assert.equal(awaitingTotal(status()), 0);
});

test('confirmsQuota requires the explicit tick', () => {
  const ticked = new FormData();
  ticked.set('confirm', 'yes');
  assert.equal(confirmsQuota(ticked), true);
  assert.equal(confirmsQuota(new FormData()), false);
});
