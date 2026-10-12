# Voxline backend

## Goal

Run AI voice agents over phone calls (inbound and outbound) for organizations.
Voxline is a self-contained, multi-tenant application: it has its own user
accounts, organizations and sign-in, and depends on no external account
service.

Each organization configures one or more voice agents: prompts, a call script,
a voice, and provider bindings for speech-to-text, text-to-speech, the LLM, and
voice-activity/turn detection. A call resolves that configuration (agent
defaults -> per-language overrides -> per-call overrides, e.g. for A/B tests or
reproducing a support complaint) and runs it end to end.

Conversational quality is the product, not an implementation detail:
- Low latency to first audio.
- Correct turn-taking: not talking over the caller, not leaving them hanging
  when they trail off mid-sentence, and not waiting indefinitely either.
- Interruption handling: when the caller barges in, the conversation history
  must reflect what was actually spoken, not what was queued to say.
- Multi-lingual by design: voice, prompts, turn-timing, and even whether
  ML-based turn detection is trusted at all are configured per language, since
  models like Smart Turn have uneven, undocumented-in-practice language coverage.

**The engine must stay provider-agnostic.** Organizations choose STT, TTS, LLM
(TTT), and VAD providers independently, at different price and quality points:
self-hosted open models and paid vendor APIs alike. Nothing in the engine may
assume a specific vendor, protocol, or that any given tier is "the" choice.
Adding a new provider must always be: one enum value, one adapter module, one
DB row, never a branch inside the engine itself.

## Tech specs

### Platform scaffold

FastAPI + async SQLAlchemy 2.0 (asyncpg) + Alembic + Redis + taskiq. Strict
layered architecture, imports only flow downward:

```
controller (api, dependencies, exceptions)
        |
application (services, worker, engine)
        |
repositories
        |
models
```

`core/` (the platform plumbing, below), `common/` (enums, types) and `utils/`
sit beside the layers and may be used from any of them. `integrations/`
(external clients) sits alongside `application` and is consumed through
registries, never imported upward.

- **`src/core/`** is the in-repo platform layer (it replaced an external
  shared library):
  - `config.py` - `Config` singleton (service prefix, debug flag, JWT settings),
    initialised by `src/settings.py` at import time. Always import
    `src.settings` before `src.core.db.*`.
  - `db/models.py` (`Base`, `BaseUUID`, `BaseRel`, `Enum`: tenant tables live in
    schema `SERVICE_PREFIX`), `db/session.py` (`SessionMaker`), `db/repository.py`
    (`BaseCRUD`).
  - `redis.py` - `RedisBase` (standalone or Sentinel), namespaced key helpers.
  - `exceptions.py`, `enums.py` (roles), `schemas.py` (`SAuthUser`).
  - `auth/` - password hashing (argon2), JWT + refresh-token helpers, cookies,
    `verify_user` / `get_current_user` / `get_permission` dependencies, and
    `PermissionManager` (role cache).
  - `control/` - control-database models, `service.py` (all user/org/membership
    logic) and `directory.py` (organization roster for background processes).
- **Two kinds of database.** One *control* database (`DB__CONTROL_NAME`, default
  `voxline_control`) holds users, organizations, memberships and refresh
  tokens (own SQLAlchemy base, own alembic env in
  `src/infrastructure/control_migrations`, config `alembic_control.ini`). Each
  organization additionally has its own *tenant* database
  `{DB__PREFIX}{organization_uuid}` with all call/agent/billing data (alembic env
  in `src/infrastructure/db/migrations`, config `alembic.ini`). `SessionMaker.get_session(org_uuid)`
  opens a tenant, `SessionMaker.get_control_session()` the control database.
- `src/sync_db.py` runs the control migrations, reads active organizations from
  the control DB and migrates every tenant database in parallel;
  `provision_organization()` does one tenant (used when an organization is created).
  `src/bootstrap.py` is the first-run CLI (control DB, first superuser, first
  organization), idempotent.
- `src/infrastructure/` holds the lifespan wiring (`startup`/`shutdown` shared by
  `main.py`, `main_hooks.py` and the taskiq worker), the Redis re-export and
  both alembic environments.
- `src/application/services/` is the business-logic layer between
  controllers and repositories, not a CRUD passthrough. Controllers stay
  thin (parse request, call a service, shape response); filtering, export,
  stats aggregation, and cross-repository orchestration live here.
- **Auth model.** Users sign in with e-mail + password (`POST /v1/auth/login`);
  the server sets two httpOnly cookies: `access_token` (HS256 JWT, ~15 min,
  claims `sub` = user id, `org` = organization uuid) and `refresh_token` (opaque,
  stored hashed in `refresh_tokens`, rotating, ~30 days; replaying a rotated token
  revokes the user's whole token family). The access token is bound to one
  organization; `change_organization` re-issues cookies for another. The caller's
  role is the `memberships.role` of that organization (control DB), cached
  in-process and in Redis for 60 s and invalidated on membership changes; a
  user with `is_superuser` is `super_admin` everywhere. Roles are
  `SharedRoleEnum` (none/admin/super_admin/owner) and `CallRoleEnum`
  (viewer/staff); the per-resource access matrix is in
  `controller/dependencies/permission.py`. Every `/v1` route except
  login/refresh/logout sits behind `verify_user`.
- Three processes plus a scheduler, not two: `main.py` (admin/HTTP API, also
  runs playground call pipelines in-process), `main_hooks.py` (the telephony
  hooks service: media WebSockets and provider status webhooks, and where the
  call engine actually runs for real calls, via `application/worker/runner.py`),
  the taskiq worker and the taskiq scheduler (`application/worker/tasks.py`,
  started by `scripts/worker.sh` / `scripts/scheduler.sh`). The worker only
  dials, dispatches campaigns, and sweeps stuck calls; it does not run the
  pipeline itself. A call is a long-lived, stateful process, not a
  request/response cycle: that is why running it lives in the hooks service,
  not a request handler. `docker compose up` also runs a one-shot `migrate`
  service (`python -m src.bootstrap`) before them.

### Worker (`src/application/worker/`)

Taskiq over Redis Streams (`broker.py`). `tasks.py` defines the actual
tasks — `dial_call`, `analyze_attempt`, and cron jobs `dispatch_campaigns`/
`sweep_calls`; `dispatch.py` holds the campaign-tick logic (settle/promote/
claim); `registry.py` tracks call routing/claim state and is shared with
the hooks service; `runner.py` is loaded by the hooks service
(`main_hooks.py`) to actually execute a call's pipeline — the worker decides
*that* a call should happen, the hooks service runs it.

### Call engine (`src/application/engine/`)

Built on **Pipecat**. Fully described by plain pydantic config
(`config.py`) with no environment reads and no ORM access, so it can be
driven from an organization's DB rows, a test fixture, or a diagnostics
command identically:

- `VoiceAgentConfig` (org's agent defaults) → `LanguageConfig` (per-language
  overrides) → `CallContext` (per-call facts and overrides) → merged by
  `resolve_profile()` into a flat `ResolvedProfile` that everything downstream
  reads. The merge is one level deep and explicit — a language replaces a
  whole section, never half of one — so "why did this call use that voice" is
  answerable by reading two rows, not by reasoning about inheritance.
- `pipeline.py` assembles the per-call Pipecat pipeline:
  `transport → STT → user aggregator (VAD + turn strategy) → silence handler
  → LLM → TTS → transport → assistant aggregator → spoken-text tracker`.
  Two orderings are load-bearing:
  - the silence handler sits upstream of the LLM (so its spoken lines reach
    TTS) and downstream of the transport's bot-speaking frames (so it knows
    when the agent is talking);
  - the spoken-text tracker sits last, after the assistant aggregator,
    because the aggregator writes the untruncated reply into context on
    interruption and the tracker must correct it afterward, not before.
- `session.py` (`CallSession`) runs one call start to finish, deliberately
  free of infrastructure (no DB/Redis access) — it reports outward
  through optional `SessionHooks` (started/transcript/finished) so
  persistence can change without the engine noticing.
- `turn/` — turn-taking as a cascade: below a floor delay, a pause is
  ignored as a breath; between floor and ceiling, a pluggable turn analyzer
  (e.g. Smart Turn) is repolled; at the ceiling the turn commits regardless,
  which is what stops a caller who trails off from being ignored. A language
  can disable the analyzer entirely and fall back to plain silence timing.
- `context/` — prompt assembly in prefix-cache-friendly layers (agent
  instructions/script → customer profile → live conversation), and
  interruption bookkeeping that rewrites assistant turns to what the caller
  actually heard.
- `capabilities.py` — real protocol/behavioral divergences between vendors
  (payload shape, end-of-utterance signaling, minimum buffer, trailing
  silence needs, language detection support) are captured as **data**
  (declared per-adapter, overridable per organization's model row), not as
  branches in client code. This is the mechanism that keeps the engine
  provider-agnostic in practice, not just in intent.
- `readiness.py` — pre-flight probe that an organization's configured agent
  can actually take a call: are its STT/TTS/LLM endpoints reachable, does
  the requested language have a voice and a prompt. Exists because a bad
  endpoint or expired key otherwise surfaces as a customer hearing silence,
  not as an error at configuration time.

### Integrations (`src/integrations/{stt,tts,ttt,vad,telephony,messaging}/`)

One `base.py` per kind with a `build_*()` factory keyed off an enum
(`src/common/enums/engine.py`). The engine only ever asks a registry for
"the adapter for this config" — it never imports a vendor module directly.
`telephony/` (jambonz, sip_bridge, twilio, websocket) and `messaging/`
(mamonty, twilio) follow the identical pattern for call transport and SMS
sending respectively.

This is the extension point for adding paid/hosted providers alongside
self-hosted ones: a new STT/TTS/TTT/VAD vendor is a new enum value, a new
adapter module implementing the relevant `base.py` protocol, and a DB row —
so an organization can pick cost/quality tradeoffs per provider kind without
any engine change.

### Configuration philosophy

- No hardcoded assumptions about which provider, tier, or protocol is "the"
  one used — every organization can mix providers per kind.
- Vendor quirks belong in configuration (`ModelConfig.capabilities`,
  per-adapter defaults), never in engine control flow — an operator should be
  able to correct a deployment that disagrees with its own documentation
  without a code release.
- Everything the engine needs is expressed as plain pydantic models with no
  env/DB coupling, so any part of it (profile resolution, pipeline assembly,
  a single call) can be exercised in a test or a diagnostics command exactly
  as it runs in production.
