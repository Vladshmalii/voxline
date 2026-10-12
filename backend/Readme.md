# Voxline backend

Backend of Voxline, a multi-tenant platform for AI voice agents that take and
place phone calls. Fully self-contained: it owns its users, organizations and
sign-in, so it needs only PostgreSQL and Redis.

## Stack

| Layer      | Technology                                         |
| ---------- | -------------------------------------------------- |
| HTTP       | FastAPI + Uvicorn / Gunicorn                       |
| Database   | PostgreSQL (asyncpg), SQLAlchemy 2.0 async         |
| Migrations | Alembic (control DB and per-organization DBs)      |
| Cache/queue| Redis (taskiq Streams, call registry, role cache)  |
| Voice      | Pipecat (STT / TTS / LLM / VAD provider adapters)  |
| Auth       | PyJWT (HS256 access token) + opaque refresh token, argon2 |
| Settings   | Pydantic v2 BaseSettings, Loguru                   |

## Architecture

Three processes plus a scheduler, one image:

| Process     | Entry point                         | Role                                                         |
| ----------- | ----------------------------------- | ------------------------------------------------------------ |
| `app`       | `src/main.py`                       | admin HTTP API (cookies), playground WebSocket               |
| `hooks`     | `src/main_hooks.py`                 | telephony media WebSockets + webhooks; runs the call pipelines |
| `worker`    | taskiq `src.application.worker.tasks:broker`    | dials calls, analysis                              |
| `scheduler` | taskiq `...tasks:scheduler`         | fires campaign dispatch and the stuck-call sweep every minute |

Data layout: one **control database** (`DB__CONTROL_NAME`) with `users`,
`organizations`, `memberships`, `refresh_tokens`, and one **tenant database per
organization** named `{DB__PREFIX}{organization_uuid}` (schema `SERVICE_PREFIX`)
with agents, calls, campaigns, billing and so on.

```
src/
  main.py, main_hooks.py        entry points (API / telephony hooks)
  bootstrap.py, sync_db.py      first-run CLI / migration runner
  settings.py                   settings + SETTINGS singleton
  core/                         platform plumbing: config, db (models/session/CRUD),
                                redis, exceptions, roles, auth/, control/
  controller/ controller_hooks/ HTTP layers (routes, dependencies)
  application/                  services, engine (Pipecat), worker (taskiq)
  repositories/ models/ schemas/ common/ utils/
  integrations/                 stt, tts, ttt, vad, telephony, messaging adapters
  infrastructure/               lifespan, db/migrations (tenant),
                                control_migrations (control)
```

Layers import strictly downward: controller -> application -> repositories ->
models; `core`, `common`, `utils`, `schemas` are usable everywhere. See
`CLAUDE.md` for the engine and layering details.

## Quick start (Docker)

```sh
cp .env.example .env        # edit SECRET_KEY, DB/Redis passwords, BOOTSTRAP_*
docker compose up --build
```

`migrate` runs first (control migrations, tenant migrations, and - with
`BOOTSTRAP_EMAIL` / `BOOTSTRAP_PASSWORD` set - the first superuser and a first
organization), then `app` (http://127.0.0.1:8086, API under `/api`), `hooks`
(8087), `worker` and `scheduler` start. It is idempotent: re-running keeps
data and applies new migrations.

## Local development

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), PostgreSQL and Redis.

```sh
uv sync
cp .env.example .env        # point DB__HOST / REDIS__HOST at localhost
python -m src.bootstrap --email admin@example.com --password 'change-me-now' --org-name Acme

uv run gunicorn src.main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080
uv run gunicorn src.main_hooks:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8081
uv run taskiq worker src.application.worker.tasks:broker
uv run taskiq scheduler src.application.worker.tasks:scheduler
```

(`scripts/*.sh` are the container entry points.) `python -m src.sync_db`
migrates the control database and every organization database without creating
anything else.

## Environment

All settings come from environment variables / `.env` (see `.env.example`).

| Variable | Meaning |
| -------- | ------- |
| `SECRET_KEY` | required; signs the session middleware and call/SMS callback tokens; JWT key is derived from it |
| `SERVICE_PREFIX` | required; tenant schema name and Redis namespace (`call`) |
| `APPLICATION_STATE` | `development` / `production` / `testing` (production: Secure cookies, no debug SQL echo) |
| `ORIGINS` | space-separated CORS origins (credentials are allowed) |
| `DB__HOST/PORT/USER/PASSWORD` | required; PostgreSQL superuser-capable role (it creates databases) |
| `DB__PREFIX` | tenant database prefix, default `org_` |
| `DB__CONTROL_NAME` | control database name, default `voxline_control` |
| `DB__POOL_*` | connection-pool tuning |
| `REDIS__TYPE/HOST/PORT/PASSWORD` | required; `standalone`, or `sentinel` with `REDIS__SENTINELS`, `REDIS__SERVICE_NAME` |
| `JWT__SECRET` | optional HS256 key; empty = derived from `SECRET_KEY` |
| `JWT__ACCESS_TTL_SECONDS`, `JWT__REFRESH_TTL_DAYS` | token lifetimes (900 s / 30 days) |
| `JWT__COOKIE_SECURE`, `JWT__COOKIE_SAMESITE`, `JWT__COOKIE_DOMAIN` | cookie attributes |
| `CALL_WORKER__MEDIA_URL` | public `wss://` base the telephony provider connects back to (worker and hooks processes) |
| `CALL_WORKER__MAX_CONCURRENT_CALLS`, `..._MAX_DIALS_PER_MINUTE`, `..._DIAL_TIMEOUT_SECONDS`, `..._MAX_CALL_SECONDS` | dispatcher limits |
| `BOOTSTRAP_EMAIL/PASSWORD/ORG_NAME` | read only by `python -m src.bootstrap` |
| `APP_WORKERS_NUM`, `HOOKS_*`, `WORKER_*` | process-manager knobs used by `scripts/` |
| `EXPORT_MAX_ROWS` | history export row cap |

## Authentication API

Everything is under `/v1` (the app is mounted at `/api`, so `/api/v1/...`). The
session lives in two httpOnly cookies, `access_token` and `refresh_token`; clients
send them automatically (`credentials: "include"`).

| Method and path | Auth | Body | Success |
| --------------- | ---- | ---- | ------- |
| `POST /v1/auth/login` | none | `{"email","password","organization_uuid"?}` | `200` session body, sets both cookies |
| `POST /v1/auth/refresh` | refresh cookie | none | `200` session body, rotates both cookies |
| `POST /v1/auth/logout` | none | none | `204`, revokes the refresh token, clears cookies |
| `GET /v1/auth/me` | session | | `200` session body |
| `GET /v1/organizations` | session | | `[{"uuid","name","role"}]` |
| `POST /v1/auth/change_organization/{uuid}` | session | none | `200` session body, re-issued cookies |
| `GET /v1/me` | session | | `{"role","billing_enabled"}` (existing endpoint) |

Session body: `{"user":{"id","email","name","is_superuser"},"organization":{"uuid","name"},"role"}`.

Errors are `{"detail": "<code>"}`: `401 token_expired` (the access token is expired,
or the access cookie is gone while a refresh cookie exists: call `/v1/auth/refresh`
and retry), `401 unauthorized` (no or unusable credentials, including a bad refresh
token), `401 invalid_credentials` (login), `401 token_invalid|token_malformed|token_invalid_signature`,
`403 forbidden`, `403 no_organization` (login with no accessible organization).

Without `organization_uuid`, login picks the user's first membership (a superuser:
the first active organization).

Account management (needs `admin`/`super_admin` in the current organization;
organization creation and the superuser flag are superuser-only):

| Method and path | Purpose |
| --------------- | ------- |
| `GET /v1/admin/organizations` | superuser: all; admin: organizations they administer |
| `POST /v1/admin/organizations` `{"name"}` | superuser; creates the organization and its tenant database (migrated) |
| `GET /v1/admin/users[?organization_uuid=]` | users (superuser: all; admin: members of their organizations) |
| `POST /v1/admin/users` `{"email","password","name"?,"is_superuser"?,"organization_uuid"?,"role"?}` | create a user; membership in `organization_uuid` (default: current organization) with `role` (default `staff`) |
| `PATCH /v1/admin/users/{id}` `{"name"?,"password"?,"is_active"?,"is_superuser"?}` | update; deactivation or a password change revokes sessions |
| `PUT /v1/admin/organizations/{uuid}/members/{user_id}` `{"role"}` | add the user to the organization or change their role |
| `DELETE /v1/admin/organizations/{uuid}/members/{user_id}` | remove the membership (`204`) |

Roles: `owner`, `admin`, `super_admin`, `none`, `staff`, `viewer`. Role lookups
are cached for up to 60 s per process; changes made through this API
invalidate the cache of the API process that handled them immediately and of
others within 60 s.

## Migrations

```sh
python -m src.sync_db                       # control DB + every tenant DB to head
# new tenant revision (against an existing tenant DB, via src/sync_db.py helpers):
python -c "from src.sync_db import generate_revision; generate_revision('<organization_uuid>')"
# new control revision:
python -c "from src.sync_db import generate_control_revision; generate_control_revision('message')"
```

Add every tenant ORM model module to `src/models/__init__.py` so alembic sees it
on `Base.metadata`; control tables live in `src/core/control/models.py`.

## Tests

```sh
uv run pytest tests/engine           # engine suite: no external services
uv run pytest tests/auth             # needs PostgreSQL only
uv run pytest tests/api tests/worker # needs PostgreSQL and Redis
```

Connection details default to `127.0.0.1` with the credentials in
`.env.example` and can be overridden with `TEST_DB_HOST/PORT/USER/PASSWORD` and
`TEST_REDIS_HOST/PORT/PASSWORD`. Suites skip themselves when a service is
unavailable. Each run creates and drops scratch databases.

## Model assignment for client organizations

Only `admin` and `super_admin` assign STT, TTS and TTT models. In the selected
organization's **Models** page, mark one active model of each kind as **Default
for new agents** (`is_default`). Selecting a new default replaces the previous
one of the same kind. The database enforces one active default per kind.

Client owners create agents without model IDs; the API assigns the organization
defaults. Existing agents keep their bindings, which administrators can change
in agent settings and language overrides. Client roles cannot change bindings,
provider endpoints, raw model request overrides or models in individual calls
and direct voice previews. Normal voice selection and agent editing remain
available according to the existing role permissions.

Deploy migration `ea92c5d78b10` to each organization database before the updated
backend (using the existing `src.sync_db` migration flow). It selects an existing
model automatically only when there is exactly one active model of that kind.
For ambiguous or missing kinds, an administrator must configure the defaults;
client agent creation returns 422 with an administrator-contact message until
all three defaults exist. Deploy the frontend together with the backend because
older forms submit model IDs that are now forbidden for client roles.

## SMS statistics and separate billing accounts

The sidebar in the Voxline frontend groups calls and messages into statistics,
billing and history pages. Existing `/dashboard`, `/billing` and `/sms` links
redirect to the corresponding new pages.

- `GET /api/v1/sms/stats/overview`: all-time message totals, today's count,
  provider-accepted messages, delivery/errors/pending counts, segments and
  all six delivery statuses. Optional `messaging_id` and exact `to` filters.
  Delivery rate is `delivered / (delivered + undelivered)`; it is null until
  there is a carrier verdict.
- `GET /api/v1/sms/stats/timeseries?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`:
  up to 90 inclusive days, including zero-activity days. The same filters
  apply. Each row contains `date`, `total`, `delivered` and `failed`
  (provider failures plus undelivered messages), grouped by creation date.
- Billing summary exposes independent `call_balance` and `sms_balance`,
  available minutes/SMS, `call_spent`/`sms_spent` and deposits per account.
  Costs are estimates using current rates; usage does not automatically
  debit either balance. The legacy `balance` field denotes the call balance.
- `POST /api/v1/billing/topup` accepts `channel: "calls" | "sms"`;
  omitted channel defaults to calls for older clients. Transaction history
  supports the same `channel` filter, plus `type=deposit` or `type=charges`
  and server-side pagination. Each transaction records its channel.

Apply migration `6dcb902f4a31` to tenant databases before running this backend
version. It transfers the old balance into calls, initializes SMS at zero,
and identifies historical SMS transactions by type or message link. Old
shared-account snapshots are preserved as `legacy_balance_after`, with
`balance_after` reserved for new transactions on each separate account.
Migration downgrade restores old snapshots and preserves both balances
by combining their funds into the previous account.

## SMS history filters

`GET /api/v1/sms` combines all supplied filters before counting and paging:

- `date_from` / `date_to`: inclusive creation days in UTC; either bound can be
  omitted. A reversed range returns 422.
- `search`: literal, case-insensitive substring of the SMS body; `to_search`
  and `sender` search the destination and sender the same way. `%` and `_`
  are ordinary characters. The legacy `to` filter still matches exactly.
- `agent_id` / `campaign_id`: the linked call's agent or campaign; `call_id`
  selects one call. `source=call` selects messages linked to calls and
  `source=manual` selects messages sent outside a call (including direct API
  sends). Deleted calls lose their link under the existing FK policy.
- `messaging_id`, `status`, `limit` (1–500), `offset` and `sort=newest|oldest`.
  Ordering uses creation time, with message ID breaking ties consistently.

List and detail responses include nullable `call_id`, `agent_id` and
`agent_name`; messages without a call or surviving agent remain visible.
Unicode search explicitly uses PostgreSQL's deterministic `und-x-icu`
collation, requiring PostgreSQL built with ICU (including the standard
PostgreSQL images and the local Homebrew installation). This also works
when the tenant database's default locale is `C`.

## Call history filters

`GET /api/v1/calls` supports the same inclusive `date_from` / `date_to`
creation days in UTC as SMS history. Existing `created_from` / `created_to`
datetime filters continue to work; explicit offsets are converted to UTC.
Reversed date or datetime ranges return 422.

- `search`: literal, case-insensitive substring of user/agent speech or the
  summary of any attempt. System/event content and JSON metadata are excluded.
  Multiple matching attempts still produce one call and one counted result.
- `client_search`: client name or destination number substring; `from_search`:
  caller number substring. As with SMS, Unicode search uses `und-x-icu` and
  escapes `%` and `_` as literal characters.
- `call_id`, `agent_id`, `campaign_id`, `client_id`, `status`, `outcome`,
  `sentiment`, `reason_category`, `direction`, and exact `language` code.
  Archived campaigns remain searchable in call history.
- `has_recording=true|false`: whether any attempt has a non-empty stored
  recording URL; this is independent of the most recent attempt's duration.
- `sort`: existing `id`, `created_at`, `status`, `duration` / `duration_seconds`
  names and their descending `-` variants. Equal values use ID as a stable
  tie-breaker; missing durations sort last in both directions. Omitting sort
  preserves descending ID order for existing clients.

All filters combine before counting and pagination. The calls and SMS pages
share the filter panel's styling and period controls; text inputs debounce,
filters reset to the first page, and late responses cannot overwrite newer
filter selections. Global call summary cards remain explicitly marked as
all-time totals, separate from the filtered result count.

## SMS and call history export

`GET /api/v1/sms/export` and `GET /api/v1/calls/export` download the history
as a file. Both accept exactly the same filters and `sort` as their list
endpoint, without `limit` / `offset`. The admin passes the filters currently
selected and the file holds exactly the rows the list would show, in the same
order. With no filters, the whole history is exported.

- `format=csv|xlsx` (default `csv`). CSV is UTF-8 with a BOM so Excel reads
  Cyrillic correctly. A text cell starting with `= + - @` gets a leading `'`
  so a spreadsheet cannot run it as a formula; normalized `+digits` phone
  numbers are left as they are. XLSX writes text strictly as strings.
- `tz` (IANA, default `UTC`) is the zone the file's datetimes are written in.
  The filters themselves stay UTC, as on the list.
- Calls are one row per call. Agent, campaign and client are resolved to names,
  and each row carries the latest attempt's start, end, duration and summary.
  Transcripts are not included. The `UUID` column appears only for
  admin/super_admin, matching the list's masking.
- Access is the same as viewing the list (`owner`, `staff`, `viewer`).
- More rows than `EXPORT_MAX_ROWS` (default 200 000) returns 422 asking to
  narrow the filters. The file is built on disk before the response starts and
  deleted after it is sent.

The list and its export share one implementation: filters are pydantic query
models in `src/schemas/filters.py`. `SmsHistoryService` and
`CallHistoryService` turn those models into SQL clauses for both the list page
and the file.
