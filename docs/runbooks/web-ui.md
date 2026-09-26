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
  (reader, deep links), `/search?q=`, `/tutor?thread={id}`, `/questions`, `/exams`,
  `/exams/{id}` (exam screen / results), `/knowledge`, `/knowledge/{concept}`,
  `/knowledge/review` (curriculum-mapping review queue), `/progress`, `/settings`
  (appearance, profile, reminders, install, export my data, delete my account).
- Server-only proxies: `POST /library/upload`, `GET /media/pages/{id}/{n}`,
  `GET /media/figures/{id}`, `POST /tutor/stream` (SSE progress, see
  [tutor runbook](tutor.md)), `POST|DELETE /settings/push` (`POST ?test` sends a test
  push), `GET|PUT|POST /exams/{id}/session` (exam reload, autosave, submit),
  `GET /settings/exports/{id}` (streams the owner's export ZIP, `no-store`).

## PWA

`static/manifest.webmanifest` declares `display: standalone`, `start_url: /`,
light theme colours with dark overrides (`user_preferences.color_scheme_dark`),
and PNG icons in `static/icons/` (192, 512, maskable 512, 180 apple-touch),
rendered from the `favicon.svg` mark. The root layout captures
`beforeinstallprompt` (`src/lib/install.svelte.ts`) so Settings can offer
*Install radbrain*; iOS gets Add-to-Home-Screen instructions. The service worker
caches only `/_app/immutable/*`, the icons, the manifest, and `/offline`
(`radbrain-shell-v3`); `src/lib/service-worker.test.ts` pins that allowlist so an
authenticated page, image, API response, or export download is never cached.

## API contracts

Types in `src/lib/types/*.ts` mirror `docs/openapi.json`; server clients live in
`src/lib/server/{tutor,study,assessment,knowledge,notifications,library}.ts` and
all go through `apiFetch`. Error mapping (`src/lib/api-state.ts`):

| API answer | UI state |
| --- | --- |
| no response / gateway error without a JSON `detail` | "Coming online" (network) |
| 503 (model runtime / VAPID not configured) | "AI is not configured on this server" |
| 429, or 503 whose detail mentions the usage limit | "AI usage window reached, try later" |
| 502 | "The AI model call failed, try again" |
| 409 on `/v1/study/today`, 404 on `/v1/study/profile` | onboarding (exam date first) |
| 409 on a question attempt | "finish your open exam first" |
| other 4xx | the API's `detail` |

Exams: the timer uses the server's `deadline_at` corrected by `server_time`.
Answers autosave (debounced 800 ms) with the exam `revision`; a 409
`stale_revision` reloads the exam, re-applies this tab's unsaved edits, and
retries. At zero the screen submits; the server grades expired exams on read.
`/exams` lists the user's exams from `GET /v1/exams` (status, counts, score),
so exams started on any device appear.
- `/offline` is prerendered static HTML served by the service worker when offline.

## Troubleshooting

- **A page shows "Coming online".** The web server could not reach the API
  (network error or a proxy 502/503/504 without a FastAPI body). Check
  `API_INTERNAL_URL` and the API container.
- **"AI is not configured on this server".** The API answered 503: the model
  runtime (Claude Code CLI) is missing on the API host.
- **Upload fails with 413 immediately.** Check `BODY_SIZE_LIMIT` on the web
  container, then Cloudflare (100 MB) and the API cap (300 MiB).
- **Page images fail to load.** `/media/*` returns 401 without a session and 404
  for unknown IDs. Check the API image route and object storage.
- **Stale UI after a deploy.** The service worker caches only hashed
  `/_app/immutable/*` assets; bump `CACHE` in `static/service-worker.js` if the
  precache list changes.
- **Push reminders.** Needs `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` on the API
  (`/v1/notifications/vapid-public-key` reports `enabled`). On iOS, the PWA must
  be installed to the Home Screen first. "Send test notification" reports how many
  devices accepted it. Payloads must never contain source text.
