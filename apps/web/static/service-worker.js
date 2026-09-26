// radbrain service worker.
//
// Caching policy (ADR 0017, 0018): only the public app shell is cached — hashed
// build assets under /_app/immutable/, the icons, the manifest, and the offline
// page. Authenticated responses (pages, /media images, /library, /api, /auth,
// uploads, export downloads, API JSON) are NEVER cached; they always go to the
// network. evals: src/lib/service-worker.test.ts pins this allowlist.
const CACHE = 'radbrain-shell-v3';
const ICONS = ['/favicon.svg', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/icon-maskable-512.png', '/icons/apple-touch-icon.png'];
const PRECACHE = ['/manifest.webmanifest', ...ICONS, '/offline'];
const PUBLIC_FILES = new Set(['/manifest.webmanifest', ...ICONS]);

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

function isCacheable(url) {
  return url.pathname.startsWith('/_app/immutable/') || PUBLIC_FILES.has(url.pathname);
}

function isPrivateResponse(response) {
  const control = response.headers.get('cache-control') || '';
  return /private|no-store/i.test(control) || response.headers.has('set-cookie');
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    // Pages are rendered per user: network only, with the static offline page as fallback.
    event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    return;
  }
  if (!isCacheable(url)) return;
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok && response.type === 'basic' && !isPrivateResponse(response)) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
    )
  );
});

// Study reminders. Payloads carry only a title, a short generic body, and a
// same-origin path — never source text or personal notes.
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = typeof payload.title === 'string' ? payload.title.slice(0, 80) : 'Time to study';
  const body = typeof payload.body === 'string' ? payload.body.slice(0, 200) : 'Your plan for today is ready.';
  const path = typeof payload.url === 'string' && payload.url.startsWith('/') && !payload.url.startsWith('//') ? payload.url : '/';
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag: 'radbrain-reminder',
      data: { url: path }
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const path = (event.notification.data && event.notification.data.url) || '/';
  const target = new URL(path, self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => new URL(w.url).origin === target.origin);
      if (open) {
        void open.navigate(target.href);
        return open.focus();
      }
      return self.clients.openWindow(target.href);
    })
  );
});
