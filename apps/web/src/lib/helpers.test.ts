import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyFailure, errorDetail } from './api-state.ts';
import { daysUntil, formatBytes, highlight, percent, snippet } from './format.ts';
import { isProcessing, stepProgress, summarizeSteps } from './pipeline.ts';
import { nextThemePref, parseThemePref, resolveTheme, themeClass, themeCookie } from './theme.ts';
import { checkUpload, uploadErrorMessage } from './upload.ts';

const step = (name: string, status: string, error: string | null = null) => ({
  step: name, status, attempts: 1, error_code: error, output_ref: null
});

test('theme preference parsing, resolution, and cookie', () => {
  assert.equal(parseThemePref('dark'), 'dark');
  assert.equal(parseThemePref('evil'), 'system');
  assert.equal(parseThemePref(undefined), 'system');
  assert.equal(resolveTheme('system', true), 'dark');
  assert.equal(resolveTheme('light', true), 'light');
  assert.equal(nextThemePref('system'), 'light');
  assert.equal(nextThemePref('dark'), 'system');
  assert.equal(themeClass('dark'), 'dark');
  assert.equal(themeClass('system'), '');
  assert.match(themeCookie('dark', true), /^radbrain_theme=dark; Path=\/; .*SameSite=Lax; Secure$/);
});

test('pipeline summary orders steps and surfaces skip reasons', () => {
  const views = summarizeSteps([
    step('render_pages', 'succeeded'),
    step('chunk', 'running'),
    step('embed_index', 'skipped', 'no_embedding_key')
  ]);
  assert.deepEqual(views.map((v) => v.state), ['done', 'running', 'skipped', 'waiting', 'waiting', 'waiting']);
  assert.equal(views[2]?.detail, 'no_embedding_key');
  assert.equal(stepProgress(views), 2 / 6);
});

test('isProcessing polls until terminal and during the post-ready vision pass', () => {
  assert.equal(isProcessing('pending'), true);
  assert.equal(isProcessing('processing'), true);
  assert.equal(isProcessing('failed'), false);
  assert.equal(isProcessing('ready', [step('parse_layout', 'running')]), true);
  assert.equal(isProcessing('ready', [step('knowledge_extraction', 'pending')]), false);
  assert.equal(isProcessing('ready', null), false);
});

test('upload checks accept study formats and warn about the tunnel limit', () => {
  assert.deepEqual(checkUpload('notes.PDF', 1000), { ok: true, warning: null });
  assert.equal(checkUpload('scan.dcm', 1000).ok, false);
  assert.equal(checkUpload('movie.mp4', 1000).ok, false);
  assert.equal(checkUpload('empty.png', 0).ok, false);
  const big = checkUpload('atlas.pdf', 150 * 1024 * 1024);
  assert.equal(big.ok, true);
  assert.ok(big.ok && big.warning?.includes('100 MB'));
  assert.equal(checkUpload('huge.pdf', 400 * 1024 * 1024).ok, false);
  assert.match(uploadErrorMessage(413), /100 MB/);
});

test('api failures degrade planned endpoints to offline', () => {
  assert.deepEqual(classifyFailure(404, 'x'), { state: 'offline', status: 404 });
  assert.deepEqual(classifyFailure(404, 'x', true), { state: 'error', status: 404, detail: 'x' });
  assert.deepEqual(classifyFailure(401, 'x'), { state: 'signed_out' });
  assert.deepEqual(classifyFailure(422, 'bad'), { state: 'error', status: 422, detail: 'bad' });
  assert.equal(errorDetail({ detail: [{ msg: 'too short' }] }, 'f'), 'too short');
  assert.equal(errorDetail('junk', 'fallback'), 'fallback');
});

test('formatters', () => {
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1536), '1.5 KB');
  assert.equal(formatBytes(150 * 1024 * 1024), '150 MB');
  assert.equal(formatBytes(null), '—');
  assert.equal(percent(0.456), '46%');
  assert.equal(daysUntil('2026-10-01', new Date(2026, 8, 26)), 5);
  assert.equal(daysUntil('bad'), null);
});

test('snippet centres on a match and highlight marks terms', () => {
  const text = `${'a '.repeat(300)}pneumothorax sign ${'b '.repeat(300)}`;
  const cut = snippet(text, 'pneumothorax', 100);
  assert.ok(cut.startsWith('…') && cut.endsWith('…') && cut.includes('pneumothorax'));
  assert.deepEqual(highlight('Deep sulcus Sign', 'sign'), [
    { text: 'Deep sulcus ', match: false },
    { text: 'Sign', match: true }
  ]);
  assert.deepEqual(highlight('a.b', '(x'), [{ text: 'a.b', match: false }]);
});
