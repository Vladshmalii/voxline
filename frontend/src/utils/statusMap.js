import {
  FiClock,
  FiPhoneCall,
  FiPhoneMissed,
  FiPhoneOff,
  FiCheckCircle,
  FiAlertTriangle,
  FiAlertCircle,
  FiSlash,
  FiLock,
  FiThumbsUp,
  FiThumbsDown,
  FiRepeat,
  FiAward,
  FiArrowUpRight,
  FiVoicemail,
  FiHelpCircle,
  FiSmile,
  FiMeh,
  FiFrown,
  FiSend,
  FiCheck,
  FiInbox,
  FiPlay,
  FiPause,
  FiEdit3,
  FiCalendar,
  FiUserX,
  FiUserCheck,
  FiMic,
  FiXOctagon,
} from 'react-icons/fi';

/**
 * The single source of truth for how a status-like enum value looks: i18n
 * label key, colour and icon.
 *
 * A raw value can mean different things depending on what it describes
 * (`completed` is an attempt, a call AND a campaign; `canceled`, `queued`,
 * `no_answer`, `failed` are shared too), so every entry lives under a KIND:
 *
 *   attempt   CallStatusEnum      one dial-to-hangup leg
 *   call      CallLifecycleEnum   the parent call across all its attempts
 *   outcome   CallOutcomeEnum     business result of the conversation
 *   sentiment SentimentEnum
 *   sms       MessageStatusEnum
 *   campaign  CampaignStatusEnum
 *   client    ClientStatusEnum
 *
 * ADDING A VALUE is one line in the right kind below (e.g. the outcome
 * `sms_sent`: `sms_sent: e('calls.outcomes.sms_sent', BLUE, FiSend)`
 * plus the en/ru label in i18n/namespaces/calls.js). Filters, tables, badges
 * and the campaign modal derive from this module, nothing else lists values.
 */
export const KINDS = {
  ATTEMPT: 'attempt',
  CALL: 'call',
  OUTCOME: 'outcome',
  SENTIMENT: 'sentiment',
  SMS: 'sms',
  CAMPAIGN: 'campaign',
  CLIENT: 'client',
};

const GRAY = '#6b7280';
const BLUE = '#2563eb';
const GREEN = '#16a34a';
const AMBER = '#d97706';
const ORANGE = '#ea580c';
const PURPLE = '#7c3aed';
const RED = '#dc2626';

const e = (labelKey, color, icon) => ({ labelKey, color, icon });

// Insertion order is the order filters and counters list the values in.
const MAP = {
  [KINDS.ATTEMPT]: {
    queued: e('calls.statuses.queued', BLUE, FiClock),
    dialing: e('calls.statuses.dialing', AMBER, FiPhoneCall),
    in_progress: e('calls.statuses.in_progress', PURPLE, FiMic),
    completed: e('calls.statuses.completed', GREEN, FiCheckCircle),
    busy: e('calls.statuses.busy', AMBER, FiPhoneOff),
    no_answer: e('calls.statuses.no_answer', GRAY, FiPhoneMissed),
    rejected: e('calls.statuses.rejected', ORANGE, FiXOctagon),
    invalid_number: e('calls.statuses.invalid_number', RED, FiAlertCircle),
    failed: e('calls.statuses.failed', RED, FiAlertTriangle),
    canceled: e('calls.statuses.canceled', GRAY, FiSlash),
  },
  [KINDS.CALL]: {
    pending: e('calls.statuses.pending', BLUE, FiClock),
    calling: e('calls.statuses.calling', PURPLE, FiPhoneCall),
    completed: e('calls.statuses.completed', GREEN, FiCheckCircle),
    exhausted: e('calls.statuses.exhausted', RED, FiRepeat),
    canceled: e('calls.statuses.canceled', GRAY, FiSlash),
    blocked: e('calls.statuses.blocked', RED, FiLock),
  },
  [KINDS.OUTCOME]: {
    interested: e('calls.outcomes.interested', GREEN, FiThumbsUp),
    not_interested: e('calls.outcomes.not_interested', GRAY, FiThumbsDown),
    call_later: e('calls.outcomes.call_later', AMBER, FiClock),
    converted: e('calls.outcomes.converted', GREEN, FiAward),
    escalated: e('calls.outcomes.escalated', PURPLE, FiArrowUpRight),
    answerphone: e('calls.outcomes.answerphone', AMBER, FiVoicemail),
    wrong_number: e('calls.outcomes.wrong_number', RED, FiPhoneOff),
    do_not_call: e('calls.outcomes.do_not_call', RED, FiUserX),
    no_answer: e('calls.outcomes.no_answer', GRAY, FiPhoneMissed),
    sms_sent: e('calls.outcomes.sms_sent', BLUE, FiSend),
    // Legacy alias of answerphone, kept so old rows still render.
    answering_machine: e('calls.outcomes.answering_machine', AMBER, FiVoicemail),
  },
  [KINDS.SENTIMENT]: {
    positive: e('calls.sentiments.positive', GREEN, FiSmile),
    neutral: e('calls.sentiments.neutral', GRAY, FiMeh),
    negative: e('calls.sentiments.negative', RED, FiFrown),
  },
  [KINDS.SMS]: {
    queued: e('sms.statuses.queued', BLUE, FiClock),
    sent: e('sms.statuses.sent', BLUE, FiSend),
    delivered: e('sms.statuses.delivered', GREEN, FiCheck),
    undelivered: e('sms.statuses.undelivered', AMBER, FiInbox),
    failed: e('sms.statuses.failed', RED, FiAlertTriangle),
    canceled: e('sms.statuses.canceled', GRAY, FiSlash),
  },
  [KINDS.CAMPAIGN]: {
    draft: e('campaigns.statuses.draft', GRAY, FiEdit3),
    scheduled: e('campaigns.statuses.scheduled', BLUE, FiCalendar),
    running: e('campaigns.statuses.running', GREEN, FiPlay),
    paused: e('campaigns.statuses.paused', AMBER, FiPause),
    completed: e('campaigns.statuses.completed', GREEN, FiCheckCircle),
    error: e('campaigns.statuses.error', RED, FiAlertTriangle),
  },
  [KINDS.CLIENT]: {
    active: e('audiences.leads.statuses.active', GREEN, FiUserCheck),
    do_not_call: e('audiences.leads.statuses.do_not_call', RED, FiUserX),
    blocked: e('audiences.leads.statuses.blocked', RED, FiLock),
  },
};

// Lookup order when a caller gives a bare value without a kind. Campaign is
// deliberately absent: its `completed` ("Завершена") must never leak onto a
// call row — pass kind=campaign explicitly (CampaignStatusBadge does).
const FALLBACK_ORDER = [
  KINDS.CALL,
  KINDS.ATTEMPT,
  KINDS.OUTCOME,
  KINDS.SENTIMENT,
  KINDS.SMS,
  KINDS.CLIENT,
];

const NEUTRAL = { labelKey: null, color: GRAY, icon: FiHelpCircle };

const prettify = (value) => String(value).replace(/_/g, ' ');

/** Meta ({ labelKey, color, icon }) for a value, or null when unknown. */
export const findStatusMeta = (value, kind) => {
  if (value === null || value === undefined || value === '') return null;
  if (kind) return MAP[kind]?.[value] || null;
  for (const k of FALLBACK_ORDER) {
    if (MAP[k][value]) return MAP[k][value];
  }
  return null;
};

/** Like findStatusMeta, but unknown values get a neutral grey/question entry. */
export const getStatusMeta = (value, kind) => findStatusMeta(value, kind) || NEUTRAL;

export const statusColor = (value, kind) => getStatusMeta(value, kind).color;

export const statusIcon = (value, kind) => getStatusMeta(value, kind).icon;

/** Translated label; falls back to the prettified raw value for unknowns. */
export const statusLabel = (t, value, kind) => {
  const meta = findStatusMeta(value, kind);
  if (meta) {
    const text = t(meta.labelKey);
    if (text && text !== meta.labelKey) return text;
  }
  return prettify(value);
};

/** Ordered raw values of a kind, e.g. for filters and counters. */
export const statusValues = (kind) => Object.keys(MAP[kind] || {});

/** [{ value, label }] for a <select>. `skip` drops legacy aliases. */
export const statusOptions = (t, kind, { skip = [] } = {}) =>
  statusValues(kind)
    .filter((v) => !skip.includes(v))
    .map((value) => ({ value, label: statusLabel(t, value, kind) }));

// Outcome aliases hidden from filters.
export const OUTCOME_FILTER_SKIP = ['answering_machine'];

// Attempt statuses a call can still change after; used to keep polling the
// open call while it is not final.
export const ACTIVE_CALL_STATUSES = ['pending', 'calling'];
export const TERMINAL_ATTEMPT_STATUSES = [
  'completed',
  'busy',
  'no_answer',
  'failed',
  'canceled',
  'rejected',
  'invalid_number',
];

