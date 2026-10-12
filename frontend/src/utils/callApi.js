import { fetchWithRefresh } from './api';
import { apiBase, apiUrlFor } from './apiBase';
import { formatApiError } from './authSession';

// Client for the call backend: a mirror of /api/openapi.json (FastAPI,
// root_path=/api). Paths carry no trailing slash — the routers are declared as
// @router.get(""), so an extra slash costs a 307 redirect.

const apiUrl = (path, query) => {
  const url = apiUrlFor(`/api/v1${path}`);
  if (query) {
    Object.entries(query).forEach(([k, v]) => {
      if (v === undefined || v === null || v === '') return;
      // Repeatable params (e.g. GET /campaigns?status=running&status=paused,
      // VOAD-36) — every other caller passes a scalar and keeps the old
      // .set() behavior untouched.
      if (Array.isArray(v)) {
        v.forEach((item) => {
          if (item !== undefined && item !== null && item !== '') url.searchParams.append(k, item);
        });
      } else {
        url.searchParams.set(k, v);
      }
    });
  }
  return url;
};

const request = async (path, { method = 'GET', body, query, isForm = false } = {}) => {
  const url = apiUrl(path, query);
  const res = await fetchWithRefresh(url.toString(), {
    method,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(formatApiError(data, res.status));
  }
  return data;
};

// A file download (history exports): same auth and refresh as request(), but
// the body is the file. The name comes from Content-Disposition (the backend
// stamps it in the export's timezone); null when a cross-origin deploy does
// not expose that header, and the caller falls back to its own.
const download = async (path, query) => {
  const res = await fetchWithRefresh(apiUrl(path, query).toString());
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(formatApiError(data, res.status));
  }
  const disposition = res.headers.get('Content-Disposition') || '';
  const filename = /filename="?([^";]+)"?/.exec(disposition)?.[1] || null;
  return { blob: await res.blob(), filename };
};

/** list/get/create/update/remove for a resource with a plain CRUD router. */
const crud = (base) => ({
  list: (query) => request(base, { query }),
  get: (id) => request(`${base}/${id}`),
  create: (body) => request(base, { method: 'POST', body }),
  update: (id, body) => request(`${base}/${id}`, { method: 'PATCH', body }),
  remove: (id) => request(`${base}/${id}`, { method: 'DELETE' }),
});

// The backend caps `limit` at 500; lookups are fetched as a single page.
export const MAX_PAGE = 500;

// The current user's role for this service (admin|super_admin|owner|staff|
// viewer|none) — drives role-based UI gating (utils/permissions.js).
export const meApi = {
  getRole: () => request('/me'),
};

// Model endpoints + keys, per organization.
export const providersApi = crud('/model-providers');

// Served STT/TTS/LLM rows. `list` filters: kind (stt|tts|ttt), is_active.
export const modelsApi = {
  defaults: () => request('/models/defaults'),
  ...crud('/models'),
  // The vendor's live voice catalogue for a TTS row — [{id, name, language}].
  // Rejects with a 422 when the adapter has none (Deepgram, Qwen3-TTS); the
  // UI uses the fixed catalogue for those adapters (utils/voiceCatalog).
  voices: (id) => request(`/models/${id}/voices`),
  // The vendor's live language list for an STT row — ["en", "multi", "ru", …].
  // Same 422 contract as `voices` (only Deepgram has a catalogue today); the
  // stt_language field stays free text either way.
  languages: (id) => request(`/models/${id}/languages`),
};

// Carrier/bridge bindings an agent dials out through.
export const telephonyApi = crud('/telephony');

// SMS routes an organization sends through. Sibling of telephony: the trunk
// that carries audio and the route that carries text are bound separately.
export const messagingApi = crud('/messaging');

// SMS: send + delivery history. `list` answers with SMessageListRead
// ({ data, count }); filters: date_from/date_to (UTC creation days),
// created_from/created_to (inclusive creation times), search,
// to (exact), to_search, sender, agent_id, campaign_id, call_id, source,
// messaging_id, status; sort: newest|oldest. Outbound only.
export const smsApi = {
  list: (query) => request('/sms', { query }),
  get: (id) => request(`/sms/${id}`),
  overview: (query) => request('/sms/stats/overview', { query }),
  timeseries: (dateFrom, dateTo, query = {}) => request('/sms/stats/timeseries', { query: { ...query, date_from: dateFrom, date_to: dateTo } }),
  // SSmsSend → 201 + SMessageRead, status `sent`. Re-read for the delivery verdict.
  send: (body) => request('/sms', { method: 'POST', body }),
  // Every message `list` would show for the same filters (no limit/offset), as
  // one file. format: csv|xlsx. 422 when more rows match than one file holds.
  export: (query, format) => download('/sms/export', { ...query, format }),
};

// Voice agents (layer 1) plus their per-language rows (layer 2) and the
// diagnostics endpoints that look at the merged result.
export const agentsApi = {
  ...crud('/voice-agents'),
  // The language rows live under the agent; there is no per-row GET — the
  // agent's detail read (SVoiceAgentDetailsRead.languages) carries them all.
  listLanguages: (agentId) => request(`/voice-agents/${agentId}/languages`),
  createLanguage: (agentId, body) =>
    request(`/voice-agents/${agentId}/languages`, { method: 'POST', body }),
  updateLanguage: (agentId, languageId, body) =>
    request(`/voice-agents/${agentId}/languages/${languageId}`, { method: 'PATCH', body }),
  removeLanguage: (agentId, languageId) =>
    request(`/voice-agents/${agentId}/languages/${languageId}`, { method: 'DELETE' }),
  // VOAD-62: SMS-tool text moderation — list() with { sms_status: 'pending' }
  // is the moderation queue itself.
  approveSms: (agentId) =>
    request(`/voice-agents/${agentId}/sms-moderation/approve`, { method: 'POST' }),
  rejectSms: (agentId) =>
    request(`/voice-agents/${agentId}/sms-moderation/reject`, { method: 'POST' }),
  // The exact ResolvedProfile a call in `language` would run with — before any call.
  profile: (agentId, language) =>
    request(`/voice-agents/${agentId}/profile`, { query: { language } }),
  // Can this agent take a call right now? `probe` also reaches the model servers.
  readiness: (agentId, { language, probe } = {}) =>
    request(`/voice-agents/${agentId}/readiness`, { query: { language, probe } }),
  // POST /voice-agents/{id}/preview-voice — synthesizes sample audio for this
  // agent's voice settings and returns raw audio bytes (not JSON), so it
  // bypasses the generic `request()` helper same as the CSV import in
  // AudiencesPage. Resolves to an object URL the caller can hand straight to
  // an <audio> element; the caller owns revoking it when done.
  previewVoice: async (agentId, { language, text } = {}) => {
    const res = await fetchWithRefresh(`${apiBase()}/api/v1/voice-agents/${agentId}/preview-voice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, text }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(formatApiError(data, res.status));
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  // POST /voice-agents/preview-voice-direct — synthesizes sample audio directly
  // for any voice and provider/adapter without needing an agent instance.
  previewVoiceDirect: async ({ voice, modelId, adapter, text, language, speed } = {}) => {
    const res = await fetchWithRefresh(`${apiBase()}/api/v1/voice-agents/preview-voice-direct`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        voice,
        model_id: modelId,
        adapter,
        text,
        language,
        speed,
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(formatApiError(data, res.status));
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
};

// Calls: the worker dials, this panel originates/cancels/inspects. `list`
// answers with SCallListRead ({ data, count }) — count is the total across
// pages; filters: agent_id, campaign_id, client_id, call_id, status, outcome,
// sentiment, reason_category, direction, language, has_recording, search
// (speech/summary), client_search (name/number), from_search, date_from/date_to
// (inclusive UTC creation days) and legacy created_from/created_to datetimes.
export const callsApi = {
  list: (query) => request('/calls', { query }),
  get: (id) => request(`/calls/${id}`),
  // Queue an outbound call (SCallCreate). 201 + SCallRead, status `queued`.
  originate: (body) => request('/calls', { method: 'POST', body }),
  // Cancel a call that has not left the queue; the backend 409s once it dials.
  cancel: (id) => request(`/calls/${id}/cancel`, { method: 'POST' }),
  // Replace a call's tags wholesale (SCallTagsUpdate, VOAD-28). `tags` must be
  // drawn from the fixed v1 vocabulary the backend validates
  // (`validate_call_tag` in src/schemas/admin.py) — anything else 422s.
  // 200 + SCallRead.
  updateTags: (id, tags) => request(`/calls/${id}/tags`, { method: 'PUT', body: { tags } }),
  // Pointer to one attempt's recording (SCallAttemptRecordingRead, VOAD-37):
  // { call_id, attempt_id, recording_url }. Admin-only; 404s (not thrown as a
  // scary error, just caught by the caller) whenever the attempt was never
  // answered or nothing has been recorded yet — the common case today, since
  // no environment captures call audio yet.
  getRecording: (callId, attemptId) => request(`/calls/${callId}/attempts/${attemptId}/recording`),
  // Aggregate counts by status and outcome, across every call — the header
  // stats strip on CallsPage. { total, statuses: {status: count}, outcomes:
  // {outcome: count} }.
  statsSummary: () => request('/calls/stats/summary'),
  // Every call `list` would show for the same filters, as one file — one row
  // per call with the latest attempt's timing and summary. format: csv|xlsx.
  export: (query, format) => download('/calls/export', { ...query, format }),
};

// Campaigns: bulk outbound dialing. `list` answers with SCampaignListRead
// ({ data, count }); filters: status (repeatable — pass an array, VOAD-36),
// agent_id, search (case-insensitive substring on name), created_from/
// created_to and starts_from/starts_to (ISO datetime bounds), sort (one of
// name|created_at|starts_at|status, optional '-' prefix for descending).
// There is no dedicated stats endpoint — counts are read by calling
// `callsApi.list` with campaign_id and a status filter and taking `.count`,
// the same way the backend itself does.
export const campaignsApi = {
  ...crud('/campaigns'),
  // Bulk contact upload (list of SCampaignContactRow): upserts clients,
  // strict-validates the script per row, creates the campaign's calls.
  // 201 + SCampaignUploadRead ({ accepted, rejected, results }).
  uploadContacts: (id, rows) => request(`/campaigns/${id}/contacts`, { method: 'POST', body: rows }),
  // Adds every member of a saved audience to this campaign — same per-row
  // checks and duplicate handling as uploadContacts above.
  addAudience: (campaignId, audienceId) =>
    request(`/campaigns/${campaignId}/audiences/${audienceId}`, { method: 'POST' }),
  // SCampaignCounters ({ total, by_status: [{status, count}] }).
  counters: (id) => request(`/campaigns/${id}/counters`),
  // SCampaignReasonBreakdown ({ total, categories: [{reason_category, count}] }).
  reasonBreakdown: (id) => request(`/campaigns/${id}/reason-categories`),
  start: (id) => request(`/campaigns/${id}/start`, { method: 'POST' }),
  pause: (id) => request(`/campaigns/${id}/pause`, { method: 'POST' }),
  complete: (id) => request(`/campaigns/${id}/complete`, { method: 'POST' }),
  // completed/error -> running|scheduled; re-queues exhausted/canceled calls.
  restart: (id) => request(`/campaigns/${id}/restart`, { method: 'POST' }),
  // Operator override: force a campaign to `error` (VOAD-36) — mirrors
  // start/pause/complete above.
  markError: (id) => request(`/campaigns/${id}/error`, { method: 'POST' }),
};

// Audiences: reusable contact lists, fed by CSV or JSON, added to campaigns
// via campaignsApi.addAudience.
export const audiencesApi = {
  list: (query) => request('/audiences', { query }),
  get: (id) => request(`/audiences/${id}`),
  create: (body) => request('/audiences', { method: 'POST', body }),
  update: (id, body) => request(`/audiences/${id}`, { method: 'PATCH', body }),
  // Cascades its membership rows; safe regardless of campaigns it fed (those
  // copied its members into their own Call rows, nothing references it back).
  remove: (id) => request(`/audiences/${id}`, { method: 'DELETE' }),
  // SAudienceMemberListRead ({ data, count }).
  listContacts: (id, query) => request(`/audiences/${id}/contacts`, { query }),
  // Bulk add (list of SCampaignContactRow-shaped rows): upserts clients,
  // upserts membership (re-adding a phone refreshes its facts).
  // 201 + SAudienceUploadRead ({ accepted, rejected, results }).
  uploadContacts: (id, rows) => request(`/audiences/${id}/contacts`, { method: 'POST', body: rows }),
  // Same, from a CSV File object (from an <input type="file">).
  uploadContactsCsv: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return request(`/audiences/${id}/contacts/csv`, { method: 'POST', body: form, isForm: true });
  },
  // VOAD-34 upload-batch history ("История загрузок") — one row per CSV/JSON
  // upload event, across both audience-targeted uploads and the VOAD-32
  // status-segment client import (`audience_id` is null for the latter).
  // Filters: audience_id, uploaded_by. Response: SAudienceUploadHistoryListRead
  // ({ data, count }); each row is SAudienceUploadHistoryRead (id, created_at,
  // audience_id, uploaded_by, filename, total_rows, valid_rows, invalid_rows).
  // src/controller/api/v1/audiences.py:39-75, src/schemas/admin.py:443-459.
  listUploads: (query) => request('/audiences/uploads', { query }),
};

// Clients: persistent per-phone facts, upserted wherever a phone enters the
// system (CSV status-segment import VOAD-32, audience/campaign contact
// uploads). `list` doubles as VOAD-34's lead table view — status/segment only
// live on Client, not on AudienceMember, see clients.py's module docstring.
// Filters: phone (substring, phone only), search (substring on phone OR
// name), status (ClientStatusEnum: active|do_not_call|blocked), segment
// (ClientSegmentEnum: cold|warm|hot), country, language, vip_status (exact
// match on all three), last_active_from/last_active_to (ISO datetime bounds),
// last_deposit_min/last_deposit_max (numeric bounds), audience_id (members of
// one audience — the closest available "leads from this upload batch" view,
// paired with audiencesApi.listUploads; see that endpoint's docstring for why
// it's approximate for the VOAD-32 client-only import, whose batches carry no
// audience_id at all). Response: SClientListRead ({ data, count }), rows are
// SClientRead (id, uuid, phone, name, status, country, language, vip_status,
// last_deposit, last_active, segment, created_at, updated_at).
// src/controller/api/v1/clients.py:33-98, src/schemas/admin.py:350-365.
export const clientsApi = {
  list: (query) => request('/clients', { query }),
  get: (id) => request(`/clients/${id}`),
  update: (id, body) => request(`/clients/${id}`, { method: 'PATCH', body }),
  // Unique non-empty countries among existing clients — feeds the Leads
  // page's country filter dropdown. src/controller/api/v1/clients.py:79-81.
  listCountries: () => request('/clients/countries'),
};

// Stats (VOAD-38, extended for the dashboard redesign): one global read-only
// snapshot — no filters, no pagination, always the whole org. SStatsOverview:
// { calls: { total, today, avg_duration_seconds, answer_rate, by_status,
// by_outcome, by_sentiment, by_reason_category, by_direction }, campaigns:
// { total, by_status, top_by_calls }, clients: { total, by_segment,
// by_status }, agents: { total, active, inactive } }. `timeseries` is a
// second, separate request — calls per day (total vs completed) for a
// date_from..date_to range (inclusive, max 90 days), for the trend chart.
// src/controller/api/v1/stats.py, src/schemas/admin.py (bottom).
export const statsApi = {
  overview: () => request('/stats/overview'),
  timeseries: (dateFrom, dateTo) =>
    request('/stats/timeseries', { query: { date_from: dateFrom, date_to: dateTo } }),
  activeGeo: () => request('/stats/active-geo'),
};

// Real-time health check and connectivity of telephony, STT/TTS/LLM models, SMS, and DB.
export const servicesApi = {
  getStatus: () => request('/services/status'),
};

// Organization billing, per-minute tariffs, balance top-ups, and transaction history.
export const billingApi = {
  getSummary: () => request('/billing/summary'),
  topUp: (body) => request('/billing/topup', { method: 'POST', body }),
  updateTariffs: (body) => request('/billing/tariffs', { method: 'PATCH', body }),
  listTransactions: (query) => request('/billing/transactions', { query }),
};

// Unified organization/company analytics for administrators.
export const adminStatsApi = {
  getStats: () => request('/admin/stats'),
};

/**
 * WS playground of an agent — not in openapi.json (WebSockets never are).
 *
 * Wire contract (src.application.services.playground on the backend):
 *   send    binary frames — raw PCM16 mono @ 16 kHz mic audio (~20 ms chunks)
 *   receive binary frames — raw PCM16 mono @ 16 kHz agent voice, plus JSON
 *           text frames: {event: "transcript", role: "user"|"assistant",
 *           text, final} for captions, {event: "clear"} on barge-in (drop
 *           buffered playback), {event: "stop"} when the session ends.
 *           The pipeline also narrates itself (AgentStateTap in
 *           src.application.engine.ui_events): {event: "state", state:
 *           "listening"|"user_speaking"|"thinking"|"speaking"}, emitted only
 *           on change, and {event: "interruption", while: "thinking"|
 *           "speaking"} right before the user_speaking state when the caller
 *           barges in ({event: "clear"} still follows separately).
 *           Once per turn, after the agent finishes (or is cut off), the
 *           latency observer reports {event: "timing", turn, waiting_user_ms,
 *           user_turn_ms, stt_ms, ttt_first_token_ms, ttt_ms, tts_ms,
 *           voice_to_voice_ms, interrupted}. Every *_ms field is null when
 *           its stage never ran (the greeting turn has null user-side
 *           fields; waiting_user_ms is null on a barge-in). stt_ms is really
 *           speech-end → transcript-commit — the turn cascade's decision
 *           time, since STT streams during speech. voice_to_voice_ms is what
 *           the caller feels; ttt_ms and tts_ms overlap under clause
 *           chunking, so they do not sum to it.
 * Auth is the same user cookie as fetch — the browser attaches it during the
 * WS handshake. Close codes: 4404 unknown agent, 4500 config failed to build.
 */
export const PLAYGROUND_SAMPLE_RATE = 16000;

export const playgroundSocketUrl = (agentId, language) => {
  const url = apiUrlFor(`/api/v1/voice-agents/${agentId}/playground`);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  if (language) url.searchParams.set('language', language);
  return url.toString();
};
