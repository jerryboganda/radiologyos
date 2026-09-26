import assert from 'node:assert/strict';
import { test } from 'node:test';
import { confirmsDeletion, downloadHref, exportStatusText, hasActiveExport, parseDecisionForm, parseDeleteForm } from './data-rights.ts';
import type { DataJob } from './types/data-rights.ts';

const ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [k, v] of entries) data.append(k, v);
  return data;
}

function job(overrides: Partial<DataJob> = {}): DataJob {
  return {
    id: ID,
    kind: 'export',
    status: 'succeeded',
    step: 'done',
    byte_size: 1024,
    detail: {},
    error_code: null,
    created_at: '2026-09-26T08:00:00Z',
    finished_at: '2026-09-26T08:01:00Z',
    expires_at: '2026-10-03T08:01:00Z',
    download_path: `/v1/me/exports/${ID}/download`,
    ...overrides
  };
}

test('account deletion needs the exact typed phrase', () => {
  assert.equal(confirmsDeletion('delete my account'), true);
  assert.equal(confirmsDeletion('  Delete My Account '), true);
  assert.equal(confirmsDeletion('delete account'), false);
  assert.equal(confirmsDeletion(null), false);
  assert.equal(parseDeleteForm(form([['confirmation', 'yes']])).ok, false);
  assert.deepEqual(parseDeleteForm(form([['confirmation', ' delete my account ']])), {
    ok: true,
    value: { confirmation: 'delete my account' }
  });
});

test('mapping decisions validate the id, the decision, and a re-code target', () => {
  assert.deepEqual(parseDecisionForm(form([['mapping_id', ID], ['decision', 'accept']])), {
    ok: true,
    value: { mappingId: ID, body: { decision: 'accept' } }
  });
  assert.equal(parseDecisionForm(form([['mapping_id', 'nope'], ['decision', 'accept']])).ok, false);
  assert.equal(parseDecisionForm(form([['mapping_id', ID], ['decision', 'maybe']])).ok, false);
  assert.equal(parseDecisionForm(form([['mapping_id', ID], ['decision', 'code']])).ok, false);
  assert.deepEqual(parseDecisionForm(form([['mapping_id', ID], ['decision', 'code'], ['curriculum_code', 'chest']])), {
    ok: true,
    value: { mappingId: ID, body: { decision: 'code', curriculum_code: 'CHEST' } }
  });
});

test('downloads go through the web server only for finished, unexpired exports', () => {
  const now = new Date('2026-09-27T00:00:00Z');
  assert.equal(downloadHref(job()), `/settings/exports/${ID}`);
  assert.equal(downloadHref(job({ status: 'running', download_path: null })), null);
  assert.equal(exportStatusText(job(), now), 'Ready to download');
  assert.equal(exportStatusText(job(), new Date('2026-10-04T00:00:00Z')), 'Expired');
  assert.equal(exportStatusText(job({ status: 'running', step: 'building' }), now), 'Collecting your data');
  assert.equal(exportStatusText(job({ status: 'failed', error_code: 'account_deleting' }), now), 'Cancelled: account deletion requested');
  assert.equal(hasActiveExport([job(), job({ status: 'queued' })]), true);
  assert.equal(hasActiveExport([job()]), false);
});
