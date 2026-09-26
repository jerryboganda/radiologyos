# 0017 — Web UI: Tailwind v4, theming, BFF media/upload proxies, planned-endpoint degradation

- Status: accepted
- Date: 2026-09-26
- Related: ADR 0006 (preview), ADR 0012 (library pipeline, BFF assertion)

`apps/web` becomes the real study UI. **New dependencies (owner authorised):**
`tailwindcss@^4` and `@tailwindcss/vite@^4` (dev), because CLAUDE.md mandates
Tailwind; there are no icon, font, or component libraries (inline SVG icons and
system font stacks only). Tokens live as CSS variables in `src/app.css` and
dark mode is class-based (`@custom-variant dark`): a head script in `app.html`
reads the `radbrain_theme` cookie (`light|dark|system`, a display preference,
never a credential) before first paint, and `hooks.server.ts` also renders the
class for explicit choices. Image stages (reader, figures) are always dark.
All API access stays server-side through `apiFetch` (signed 60 s assertion);
the browser never sees a token. Page and figure images go through
`/media/pages/{source}/{page}` and `/media/figures/{id}`, which stream the API
bytes unchanged (no re-encode or downscale) with `Cache-Control: private,
max-age=300`. Uploads go browser → `POST /library/upload` → API as a streamed
multipart body (`duplex: 'half'`), so adapter-node needs `BODY_SIZE_LIMIT=310M`
(set in the Dockerfile); Cloudflare still caps public requests at 100 MB and the
UI warns about files above that. Pages for planned services (tutor, study,
questions, exams, knowledge, notifications) call the planned `/v1/...` paths
through typed clients in `src/lib/server/` and treat 404/405/5xx/network
failures as "coming online" rather than errors. The service worker caches only
`/_app/immutable/*`, the icon, the manifest, and the static `/offline` page;
pages, `/media`, and API responses are never cached. It also handles Web Push
display with same-origin click targets. The legacy `/preview` route is kept
(ADR 0006) with its old global CSS imported only by that page and
`data-sveltekit-reload` on its links, so those globals never leak into the app.
