// Pins the service worker's caching policy: only the public shell is cacheable,
// never an authenticated page, image, API response, upload, or export download.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const ORIGIN = 'https://radbrain.example';

type Worker = {
  isCacheable: (url: URL) => boolean;
  isPrivateResponse: (response: { headers: Headers }) => boolean;
  PRECACHE: string[];
};

function loadWorker(): Worker {
  const source = readFileSync(new URL('../../static/service-worker.js', import.meta.url), 'utf8');
  const context = vm.createContext({
    URL,
    Headers,
    self: { addEventListener: () => undefined, location: { origin: ORIGIN } }
  });
  vm.runInContext(`${source}\n;globalThis.__sw = { isCacheable, isPrivateResponse, PRECACHE };`, context);
  return (context as unknown as { __sw: Worker }).__sw;
}

test('only hashed assets, icons, and the manifest are cacheable', () => {
  const sw = loadWorker();
  for (const path of ['/_app/immutable/chunks/app.js', '/manifest.webmanifest', '/favicon.svg', '/icons/icon-512.png']) {
    assert.equal(sw.isCacheable(new URL(path, ORIGIN)), true, path);
  }
  for (const path of [
    '/',
    '/settings',
    '/settings/exports/3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b',
    '/media/pages/x/1',
    '/media/figures/x',
    '/library/upload',
    '/api/health',
    '/auth/callback',
    '/knowledge/review',
    '/icons/../settings'
  ]) {
    assert.equal(sw.isCacheable(new URL(path, ORIGIN)), false, path);
  }
});

test('the precache holds no authenticated route', () => {
  const sw = loadWorker();
  // Copy out of the vm realm so the comparison is between plain local arrays.
  const unexpected = [...sw.PRECACHE].filter(
    (path) => !['/offline', '/manifest.webmanifest'].includes(path) && !/^\/(favicon\.svg|icons\/)/.test(path)
  );
  assert.deepEqual(unexpected, []);
});

test('private or cookie-setting responses are never stored', () => {
  const sw = loadWorker();
  assert.equal(sw.isPrivateResponse({ headers: new Headers({ 'cache-control': 'private, max-age=300' }) }), true);
  assert.equal(sw.isPrivateResponse({ headers: new Headers({ 'cache-control': 'no-store' }) }), true);
  assert.equal(sw.isPrivateResponse({ headers: new Headers({ 'set-cookie': 'a=b' }) }), true);
  assert.equal(sw.isPrivateResponse({ headers: new Headers({ 'cache-control': 'public, max-age=31536000' }) }), false);
});
