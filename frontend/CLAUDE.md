# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Voxline admin panel — a React 18 + Vite single-page app for the Voxline voice-agent platform backend (header + sidebar shell, light/dark theme, en/ru i18n, styled-components, violet accent). It is a standalone application: one backend, one origin for every API call, and its own login page.

| Tab | Backend resource |
|---|---|
| Voice agents | `/v1/voice-agents` + per-agent page: languages (`…/languages`), readiness (`…/readiness`), resolved-profile preview (`…/profile`), full settings editor |
| — Playground | `WS /v1/voice-agents/{id}/playground` — talk to the agent from the browser: PCM16 mono 16 kHz both ways + JSON caption/clear/stop frames, pipeline state narration (`state`: listening/user_speaking/thinking/speaking, `interruption`) and per-turn latency reports (`timing`) (not in openapi.json) |
| Calls | `/v1/calls` (paginated, agent/status/direction/number filters, originate + cancel, transcript viewer) |
| Models | `/v1/models` |
| Providers | `/v1/model-providers` |
| Telephony | `/v1/telephony` |
| Messaging | `/v1/messaging` — an organization's SMS routes (sibling of telephony: the trunk carrying audio and the route carrying text are bound separately) |
| SMS | `/v1/sms` — send + delivery history for the routes above |
| Users & Organizations | `/v1/admin/organizations`, `/v1/admin/users`, `/v1/admin/organizations/{uuid}/members/{user_id}` — admin / super_admin only |

## Commands

```bash
npm install
npm start          # dev server on http://localhost:3000 (/api is proxied to VITE_DEV_PROXY_TARGET, default http://localhost:8086)
npm run build      # production build to dist/
npm run preview    # preview the production build
npm run lint:js    # eslint src/**/*.{js,jsx}
npm test           # node --test (Node built-in runner; discovers tests/*.test.mjs)
```

Run a single test file with `node --test tests/historyDates.test.mjs`.

## Environment (`.env`)

| Var | Meaning | Default |
|---|---|---|
| `VITE_API_URL` | Backend host for everything: REST `/api/v1/...` and the WS playground. Unset → `http://localhost:8086`; set to an empty string → same origin (relative URLs, e.g. behind the nginx `/api` proxy or the Vite dev proxy). | `http://localhost:8086` |
| `VITE_DEV_PROXY_TARGET` | Dev only: where the Vite dev server forwards `/api` (useful with `VITE_API_URL=""`, no CORS needed). | `http://localhost:8086` |

Docker: `VITE_API_URL` is a build arg (default empty = same origin); the nginx image proxies `/api/` (incl. WebSocket upgrade) to `API_UPSTREAM` at runtime (default `http://backend:8086`).

## Architecture

### Path aliases (`vite.config.js`)

`app`, `components`, `pages`, `contexts`, `i18n`, `theme`, `utils`, `data` all resolve to `src/<name>` — import with these instead of relative paths climbing out of a directory.

### Auth (`src/utils/api.js`, `src/utils/authApi.js`, `src/pages/LoginPage.jsx`, `src/app/AppLayout.jsx`)

Cookie-based, issued by the backend; tokens (`access_token`, `refresh_token`) are httpOnly and the frontend never reads them.

- `/login` (in-app page, outside the shell): `POST /auth/login {email, password}`; if `GET /organizations` returns more than one, an org picker follows (`POST /auth/change_organization/{uuid}`), then a full load of `?next=` (sanitised to a same-app path). A user who already has a session is forwarded straight away.
- `installGlobalAuthenticatedFetch()` monkey-patches `window.fetch`: any request to the backend (`/api/v1/...` under `VITE_API_URL` or relative; the login/refresh/logout session paths excluded) rides with `credentials: 'include'`. A 401 whose `detail` is `token_expired` gets exactly one deduped `POST /auth/refresh` and a retry (parallel 401s share one refresh); any other 401 (`unauthorized`, `token_invalid`, …) or a failed refresh redirects to `/login?next=<current path>`.
- `AppLayout` gates the app zone on `GET /auth/me` (`{user, organization, role}`) and then `GET /me` (`{role, billing_enabled}`) for the role that drives UI gating; the combined object is the `UserContext` value.
- Organization switcher (header): `GET /organizations`, `POST /auth/change_organization/{uuid}`; on success the app does a full reload so every page restarts in the new organization's context. Sign out: `POST /auth/logout`, then `/login`.
- The WS playground authenticates with the same cookie during the handshake; the page fires one authenticated fetch right before connecting so the access token is fresh (a WebSocket can't go through the refresh wrapper).
- `UsersPage` (`/users`, `canManageUsers` = admin/super_admin): organizations list/create, users list/create/edit (name, password, active, superuser) and per-organization role assignment via `PUT/DELETE /admin/organizations/{uuid}/members/{user_id}`.

### Permissions (`src/utils/permissions.js`)

Role-based UI gating that mirrors the backend's access matrix — this is defense-in-depth only, the backend is authoritative on every request. Roles: `admin`/`super_admin` (full access), `owner`, `staff`, `viewer`, `none`. Use `canView`/`canWrite`/`hasFullAccess` and the resource-specific helpers (`canManageAgents`, `canDeleteAgents`, `canSendSms`, `canManageUsers`, …) rather than checking role strings directly — several resources have asymmetric view/write/delete tiers (e.g. agent delete is owner-only even though agent write is owner+staff).

### i18n (`src/i18n/`)

- `registry.js` holds the message registry (bottom of the dependency graph — holds no namespace imports, to avoid a cycle). `LOCALES = ['en', 'ru']`.
- Each feature registers its own namespace module under `src/i18n/namespaces/` via `registerMessages(namespace, { en: {...}, ru: {...} })`; `namespaces/index.js` imports all of them so importing anything from `i18n` guarantees the catalogue is populated.
- Lookup is dotted-path (`t('steps.branchLabels')`); missing-in-active-locale falls back to `DEFAULT_LOCALE`, missing-everywhere returns the key itself so gaps are visible in the UI.
- A message value can be a function of `params` for plurals/conditional text instead of plain `{placeholder}` interpolation.
- `resolveText(t, spec, slot)` reads a translatable slot off a declarative spec (form field/table column): `labelKey` wins over a literal `label`, so specs stay plain data and the render layer decides the language.
- `translate()` / `detectLocale()` exist for use outside the React tree (class components, plain modules); inside components prefer the `useI18n` hook so locale switches re-render.

### Routing & shell (`src/app/`)

`navItems.js` drives the sidebar (`Sidebar.jsx`) and route table; pages are lazy-loaded. `AppLayout.jsx` is the auth gate + shell (header, sidebar, theme). `Header.jsx` / `OrgSwitcher.jsx` / `UserMenu.jsx` / `ToggleTheme.jsx` are shell chrome.

### Forms

Resource forms are declarative specs rendered by a shared `ResourceForm`-style renderer (see `agentFields.js`, `campaignFields.js`) rather than hand-rolled JSX per field — specs support conditional visibility (`showIf`) and i18n via `labelKey`/`hintKey` (see `resolveText` above). There is no PropTypes usage in this JS project; form specs are the validation layer instead (`react/prop-types` is off in `.eslintrc.cjs`).

### Key utils (`src/utils/`)

- `api.js` — the authenticated-fetch wrapper described above.
- `apiBase.js` — the single backend host (`VITE_API_URL`) and absolute-URL helper.
- `callApi.js` — typed request helpers for the resource endpoints.
- `authApi.js` — login/logout/me/organizations and the `/admin/*` user & organization management calls.
- `authSession.js` — pure session helpers (refreshable-401 rule, `?next=` sanitising, API-URL matching, error formatting); unit-tested in `tests/authSession.test.mjs`.
- `historyDates.js` / `historyFilters.js` — shared date-range/filter logic for the Calls and SMS history views (period presets resolve to explicit UTC `date_from`/`date_to`).
- `permissions.js` — see above.
- `voiceCatalog.js` / `useVoiceLabels.js` — voice catalog loading with in-memory caching (TTL) and prefetching, since the catalog is reused across agent configuration pages.
- `playgroundPlayback.js` — audio playback/encoding helpers for the WS playground.
