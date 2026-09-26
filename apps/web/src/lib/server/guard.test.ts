import assert from 'node:assert/strict';
import test from 'node:test';
import { applyThemeClass, requiresSession, SESSION_ENDPOINTS, THEME_PLACEHOLDER } from './guard.ts';

test('refuses every guarded endpoint without a session', () => {
  for (const path of [
    '/media/pages/abc/1',
    '/media/figures/x',
    '/library/upload',
    '/tutor/stream',
    '/settings/exports/123',
    '/settings/alerts/ack'
  ]) {
    assert.equal(requiresSession(path, false), true, path);
  }
});

test('lets a signed-in user through guarded endpoints', () => {
  for (const prefix of SESSION_ENDPOINTS) assert.equal(requiresSession(prefix, true), false, prefix);
});

test('leaves pages and public endpoints to their own guards', () => {
  for (const path of ['/', '/library', '/library/abc', '/settings', '/auth/login', '/api/health', '/tutor']) {
    assert.equal(requiresSession(path, false), false, path);
  }
});

test('matches by prefix only, not by substring', () => {
  assert.equal(requiresSession('/x/media/pages/1', false), false);
  assert.equal(requiresSession('/medias', false), false);
});

test('fills the theme placeholder once for each preference', () => {
  const html = `<html class="${THEME_PLACEHOLDER}"><body></body></html>`;
  assert.equal(applyThemeClass(html, 'dark'), '<html class="dark"><body></body></html>');
  assert.equal(applyThemeClass(html, 'light'), '<html class=""><body></body></html>');
  assert.equal(applyThemeClass(html, 'system'), '<html class=""><body></body></html>');
});

test('leaves a chunk without the placeholder unchanged', () => {
  assert.equal(applyThemeClass('<p>chunk</p>', 'dark'), '<p>chunk</p>');
});
