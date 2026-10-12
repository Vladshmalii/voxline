# Voxline Frontend

React 18 + Vite admin panel for the Voxline voice-agent platform: header +
sidebar shell, light/dark theme, en/ru i18n, styled-components, violet accent.
A standalone app with its own login page, talking to a single backend.

## Sections

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

## Run

```bash
npm install
npm start      # dev server on http://localhost:3000
npm run build  # production build to dist/
npm run lint:js
npm test
```

## Environment (`.env`, see `.env.example`)

| Var | Meaning | Default |
|---|---|---|
| `VITE_API_URL` | Backend host (`/api/v1/...`, WS playground included). Empty string = same origin. | `http://localhost:8086` |
| `VITE_DEV_PROXY_TARGET` | Dev only: target of the Vite `/api` proxy (use with `VITE_API_URL=""`). | `http://localhost:8086` |

## Docker

```bash
docker build -t voxline-frontend .                      # same-origin build (VITE_API_URL empty)
docker run -p 8080:80 -e API_UPSTREAM=http://backend:8086 voxline-frontend
```

nginx serves the SPA and proxies `/api/` (WebSocket upgrade included) to
`API_UPSTREAM`. Pass `--build-arg VITE_API_URL=https://api.example.com` to call
a backend directly instead.

## Auth

Cookie-based (httpOnly `access_token` + `refresh_token` issued by the backend):

- `/login` is an in-app page: email + password, then an organization picker
  when the account belongs to several; unauthenticated users are redirected
  there with `?next=`.
- `window.fetch` is patched so backend requests carry credentials; a `401`
  with `detail: token_expired` triggers one deduped `POST /auth/refresh` and a
  retry, any other 401 goes to `/login`.
- `AppLayout` gates the app on `GET /auth/me` and reads the role from `GET /me`.
- Organization switcher (header): `GET /organizations`,
  `POST /auth/change_organization/{uuid}`, then a full reload. Sign out calls
  `POST /auth/logout` and returns to `/login`.
- Admins (`admin` / `super_admin`) get a "Users & Organizations" page for
  managing organizations, users and per-organization roles.
- The WS playground authenticates with the same cookie during the handshake.
