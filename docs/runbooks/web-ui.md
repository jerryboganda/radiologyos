# Web UI runbook

Scope: `apps/web` (SvelteKit 2, Svelte 5, Tailwind v4, adapter-node). Decision
record: [ADR 0017](../decisions/0017-web-ui.md).

## Local checks (lightweight only)

```bash
npm --prefix apps/web ci
npm --prefix apps/web run check   # svelte-check, must be 0 errors / 0 warnings
npm --prefix apps/web test        # node --test over src/**/*.test.ts (pure helpers)
npm --prefix apps/web run build   # adapter-node output in apps/web/build
```

Browser/E2E and staging checks run in GitHub Actions only (ADR 0005/0008).

## Runtime configuration

| Variable | Purpose |
| --- | --- |
| `WEB_API_SECRET` | Shared with the API; signs the per-request user assertion. |
| `API_INTERNAL_URL` | API base URL reachable from the web container. |
| `BODY_SIZE_LIMIT` | Must exceed the API upload cap; the Dockerfile sets `310M`. |
| `PREVIEW_ENABLED` | Shows the Settings link to the non-release `/preview`. |

Uploads over 100 MB fail on the public hostname (Cloudflare request limit,
HTTP 413). Split the file or upload from the local network.

## Routes

- `/` Today (sign-in screen when signed out), `/library`, `/library/{id}?page=N&block=M`
  (reader, deep links), `/search?q=`, `/tutor`, `/questions`, `/exams`, `/knowledge`,
  `/progress`, `/settings`.
- Server-only proxies: `POST /library/upload`, `GET /media/pages/{id}/{n}`,
  `GET /media/figures/{id}`, `POST|DELETE /settings/push`.
- `/offline` is prerendered static HTML served by the service worker when offline.

## Troubleshooting

- **A page shows "Coming online".** The planned API endpoint returned
  404/405/5xx or was unreachable. Deploy that service; no web change is needed.
- **Upload fails with 413 immediately.** Check `BODY_SIZE_LIMIT` on the web
  container, then Cloudflare (100 MB) and the API cap (300 MiB).
- **Page images fail to load.** `/media/*` returns 401 without a session and 404
  for unknown IDs. Check the API image route and object storage.
- **Stale UI after a deploy.** The service worker caches only hashed
  `/_app/immutable/*` assets; bump `CACHE` in `static/service-worker.js` if the
  precache list changes.
- **Push reminders.** Needs the API's `/v1/notifications/vapid-public-key`. On
  iOS, the PWA must be installed to the Home Screen first. Payloads must never
  contain source text.
