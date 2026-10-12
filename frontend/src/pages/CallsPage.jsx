import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import styled from 'styled-components';
import { HiArrowPath, HiInformationCircle, HiChevronDown, HiAdjustmentsHorizontal, HiXMark } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { StatusBadge } from 'components/badges';
import { KINDS, statusOptions, ACTIVE_CALL_STATUSES } from 'utils/statusMap';
import { useAutoRefresh } from 'utils/useAutoRefresh';
import { JsonView } from 'components/JsonView';
import { Modal } from 'components/Modal';
import { Pagination } from 'components/Pagination';
import { toast } from 'components/Toaster';
import { HistoryExport } from 'components/HistoryExport';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
import { CallRecordingPlayer } from 'components/CallRecordingPlayer';
import { useUser } from 'contexts/UserContext';
import { canAssignModels, canWrite, hasFullAccess } from 'utils/permissions';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  Select,
  TextInput,
  PrimaryButton,
  SecondaryButton,
  DangerButton,
  Badge,
  TableContainer,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  EmptyState,
  EmptyStateTitle,
  EmptyStateText,
  formatDateTime,
} from 'components/ui';
import { callsApi, agentsApi, campaignsApi } from 'utils/callApi';
import { normalizeMessages } from 'utils/transcript';
import { PERIODS, periodRange, historyDateQuery, loadFilterOptions } from 'utils/historyFilters';
import {
  FilterCard, FilterHeader, FilterGrid, Filter, SearchFilter, StatusFilter,
  PeriodBar, PeriodButton, FilterNote, AdvancedToggle, AdvancedGrid,
  Chips, Chip, ResultsBar, RefreshButton,
} from 'components/HistoryFilters';

// Calls are created (originated) and canceled, never edited, so this page
// mirrors CrudPage's chrome by hand rather than reusing it: CrudPage has no
// filters, no server-side paging and no detail view, which are the whole
// point here. The list answers with SCallListRead ({ data, count }).
const PAGE_SIZE = 50;

// CallLifecycleEnum — the parent Call's own status; a leg's CallStatusEnum
// (queued/dialing/in_progress/...) only appears per attempt, in the detail.
const STATUSES = ['pending', 'calling', 'completed', 'canceled', 'exhausted', 'blocked'];
const OUTCOMES = [
  'interested',
  'converted',
  'not_interested',
  'call_later',
  'answerphone',
  'escalated',
  'wrong_number',
  'do_not_call',
  'no_answer',
  'sms_sent',
];
const REASON_CATEGORIES = [
  'bonus_conditions',
  'payment_problem',
  'lost_interest',
  'competitor',
  'technical_issue',
  'responsible_gaming',
  'other',
];

// A call is cancelable only before its leg starts dialing — the backend 409s
// once an attempt exists past `queued`. Keep in sync with POST
// /calls/{id}/cancel and CallCRUD.cancel.
const CANCELABLE_STATUSES = new Set(['pending']);

// Fixed v1 tag vocabulary (VOAD-28). Byte-for-byte the same strings as
// CALL_TAG_* / validate_call_tag in src/schemas/admin.py on the backend — the
// PUT /calls/{id}/tags endpoint 422s on anything else, so these are offered as
// checkboxes rather than free text. CALL_TAG_FINISHED may also be stored with
// a free-text ": <result>" suffix, which gets its own text input below.
const CALL_TAG_NOT_ANSWERED = 'Клиент не ответил';
const CALL_TAG_ANSWERED = 'Клиент ответил';
const CALL_TAG_FINISHED = 'Разговор завершён';
const CALL_TAG_OPTED_OUT = 'Отказался от дальнейших звонков';
const SIMPLE_CALL_TAGS = [CALL_TAG_NOT_ANSWERED, CALL_TAG_ANSWERED, CALL_TAG_OPTED_OUT];
const FINISHED_TAG_PREFIX = `${CALL_TAG_FINISHED}: `;

// The stored tag strings above are API values and stay Russian in every
// locale; only the label shown to the user is localised. The free-text
// ": <result>" suffix of CALL_TAG_FINISHED is user content and kept verbatim.
const CALL_TAG_LABEL_KEYS = {
  [CALL_TAG_NOT_ANSWERED]: 'calls.tagLabels.notAnswered',
  [CALL_TAG_ANSWERED]: 'calls.tagLabels.answered',
  [CALL_TAG_FINISHED]: 'calls.tagLabels.finished',
  [CALL_TAG_OPTED_OUT]: 'calls.tagLabels.optedOut',
};
const callTagLabel = (t, tag) => {
  if (CALL_TAG_LABEL_KEYS[tag]) return t(CALL_TAG_LABEL_KEYS[tag]);
  if (tag.startsWith(FINISHED_TAG_PREFIX)) {
    return `${t(CALL_TAG_LABEL_KEYS[CALL_TAG_FINISHED])}: ${tag.slice(FINISHED_TAG_PREFIX.length)}`;
  }
  return tag;
};

// Splits a call's stored `tags` list back into editor state: which simple
// tags are set, whether CALL_TAG_FINISHED is set, and its free-text result
// suffix (if any). Any tag outside the v1 vocabulary (shouldn't happen post
// validation, but a call may predate it) is ignored here — it still shows up
// in the read-only chip list, just not as a checkbox.
const parseCallTags = (tags) => {
  const list = Array.isArray(tags) ? tags : [];
  let finished = false;
  let finishedResult = '';
  const simple = [];
  list.forEach((tag) => {
    if (tag === CALL_TAG_FINISHED) {
      finished = true;
    } else if (tag.startsWith(FINISHED_TAG_PREFIX)) {
      finished = true;
      finishedResult = tag.slice(FINISHED_TAG_PREFIX.length);
    } else if (SIMPLE_CALL_TAGS.includes(tag)) {
      simple.push(tag);
    }
  });
  return { simple, finished, finishedResult };
};

const EMPTY_TEXT = { search: '', client_search: '', from_search: '', call_id: '', language: '' };
const EMPTY_FILTERS = {
  ...EMPTY_TEXT, agent_id: '', campaign_id: '', status: '', attempt_status: '', outcome: '',
  reason_category: '', sentiment: '', direction: '', has_recording: '',
  date_from: '', date_to: '', sort: '-created_at',
};
const SORTS = ['-created_at', 'created_at', '-duration', 'duration', 'status', '-status', '-id', 'id'];

const StatsGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
`;

const StatCard = styled.div`
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
`;

const StatLabel = styled.div`
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: ${({ theme }) => theme.colors.secondary};
  letter-spacing: 0.04em;
`;

const StatValue = styled.div`
  font-size: 18px;
  font-weight: 700;
  color: ${({ theme, $color }) => $color || theme.colors.primary};
`;

const SortableHeader = styled(TableHeaderCell)`
  cursor: pointer;
  user-select: none;
  &:hover {
    color: ${({ theme }) => theme.colors.primary};
  }
`;

const DetailGrid = styled.div`
  display: grid;
  grid-template-columns: minmax(120px, max-content) 1fr;
  gap: 10px 16px;
  align-items: baseline;
  margin-bottom: 18px;
`;

const DetailKey = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  text-transform: uppercase;
  letter-spacing: 0.04em;
`;

const DetailValue = styled.div`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  word-break: break-word;
`;

const LeadLink = styled.button`
  display: inline;
  margin-left: 8px;
  padding: 0;
  border: none;
  background: none;
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.accentNeon || theme.colors.secondary};
  text-decoration: underline;
  cursor: pointer;
`;

// Plain native `title` tooltip (no dedicated Tooltip component in this app) —
// clarifies that "attempts made" counts one Call's own retry cycle, not every
// time this phone number has ever been dialed (VOAD-25's original confusion:
// re-uploading a contact starts a new Call/cycle instead of adding to this one).
const InfoIcon = styled(HiInformationCircle)`
  display: inline-block;
  vertical-align: -2px;
  margin-left: 4px;
  color: ${({ theme }) => theme.colors.secondary};
  cursor: help;
`;

const SectionLabel = styled.div`
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  text-transform: uppercase;
  letter-spacing: 0.04em;

  span {
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    color: ${({ theme }) => theme.colors.muted};
  }
`;

const Section = styled.div`
  margin-bottom: 16px;
`;

const TagsRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
`;

const TagsEditor = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 10px 0;

  label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: ${({ theme }) => theme.colors.primary};
  }

  input[type='text'] {
    margin-left: 24px;
    min-width: 260px;
  }
`;

// The transcript: what the caller actually heard, as chat bubbles.
const Bubbles = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

// VOAD-58: 'event' (a synthetic status row, e.g. a language switch) and
// 'tool' (a friendly rendering of a function call) each get their own
// distinct color so they read as "what happened" rather than "who spoke" —
// separate from the user/assistant dialogue.
const Bubble = styled.div`
  align-self: ${({ $role }) => ($role === 'assistant' ? 'flex-start' : $role === 'user' ? 'flex-end' : 'center')};
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
  color: ${({ $role, theme }) => ($role === 'tool' ? theme.colors.accentNeon : theme.colors.primary)};
  background: ${({ $role, theme }) =>
    $role === 'assistant'
      ? theme.colors.hover
      : $role === 'user'
        ? `${theme.colors.accent}22`
        : $role === 'tool'
          ? `${theme.colors.accentNeon}18`
          : 'transparent'};
  border: 1px solid ${({ $role, theme }) => ($role === 'event' ? theme.colors.border : 'transparent')};
  font-style: ${({ $role }) => ($role === 'event' ? 'italic' : 'normal')};
`;

const BubbleRole = styled.div`
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: ${({ theme }) => theme.colors.muted};
  margin-bottom: 2px;
`;

// The engine's own vocabulary ("user"/"assistant"/"event", see
// src.application.engine.context.assembly and worker/runner.py on the
// backend) means "who fed the LLM this turn", not who a person listening
// back would say spoke — label each turn by who actually said it instead.
const ROLE_LABELS = {
  user: 'Client',
  assistant: 'Agent',
  event: 'Event',
  tool: 'Action',
};
const roleLabel = (role, t) => {
  if (t) {
    const key = `calls.roles.${role}`;
    const translated = t(key);
    if (translated && translated !== key) return translated;
  }
  return ROLE_LABELS[role] || role || '?';
};

// SCallCreate — flat fields, pinned on the Call row at creation and rendered
// into the script the same way for every attempt.
const originateFields = (agents, canAssign) => [
  {
    name: 'agent_id',
    labelKey: 'calls.fields.agent',
    type: 'select',
    asNumber: true,
    required: true,
    options: (agents || []).map((a) => ({ value: a.id, label: `${a.name} (#${a.id})` })),
  },
  {
    name: 'to_number',
    labelKey: 'calls.fields.toNumber',
    type: 'text',
    required: true,
    placeholderKey: 'calls.filters.toNumberPlaceholder',
  },
  {
    name: 'from_number',
    labelKey: 'calls.fields.fromNumber',
    type: 'text',
    nullable: true,
    hintKey: 'calls.fields.fromNumberHint',
  },
  {
    name: 'language',
    labelKey: 'calls.fields.language',
    type: 'text',
    nullable: true,
    hintKey: 'calls.fields.languageHint',
  },
  {
    name: 'name',
    labelKey: 'calls.fields.customerName',
    type: 'text',
    nullable: true,
  },
  {
    name: 'attributes',
    labelKey: 'calls.fields.customerAttributes',
    type: 'json',
    emptyValue: {},
    rows: 3,
    hintKey: 'calls.fields.customerAttributesHint',
  },
  {
    name: 'bonuses',
    labelKey: 'calls.fields.bonuses',
    type: 'json',
    emptyValue: [],
    rows: 3,
    hintKey: 'calls.fields.bonusesHint',
  },
  { name: 'player_id', labelKey: 'calls.fields.playerId', type: 'text', nullable: true },
  { name: 'vip_status', labelKey: 'calls.fields.vipStatus', type: 'text', nullable: true },
  { name: 'last_deposit', labelKey: 'calls.fields.lastDeposit', type: 'number', nullable: true },
  {
    name: 'last_active',
    labelKey: 'calls.fields.lastActive',
    type: 'text',
    nullable: true,
    hintKey: 'calls.fields.lastActiveHint',
  },
  { name: 'country', labelKey: 'calls.fields.country', type: 'text', nullable: true },
  { name: 'timezone', labelKey: 'calls.fields.timezone', type: 'text', nullable: true },
  {
    name: 'overrides',
    labelKey: 'calls.fields.overrides',
    type: 'json',
    nullable: true,
    rows: 4,
    hintKey: 'calls.fields.overridesHint',
  },
].filter((field) => canAssign || !['overrides', 'from_number'].includes(field.name));

export const CallsPage = () => {
  const { theme } = useTheme();
  const { t, locale } = useI18n();
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const canManage = canWrite('calls', user?.role);
  const fullAccess = hasFullAccess(user?.role); // caller ID (from number) is admin-only

  const [agents, setAgents] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [lookupError, setLookupError] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [textInputs, setTextInputs] = useState(EMPTY_TEXT);
  const [advanced, setAdvanced] = useState(false);
  const statsRequestId = useRef(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [detail, setDetail] = useState(null); // { id, data?, error? }
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);

  const [originate, setOriginate] = useState(false);
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [originating, setOriginating] = useState(false);

  useEffect(() => {
    let canceled = false;
    Promise.allSettled([
      [agentsApi, setAgents],
      [campaignsApi, setCampaigns, { include_archived: true }],
    ].map(async ([api, update, query]) => {
      const data = await loadFilterOptions(api, query, () => canceled);
      if (!canceled) update(data);
    })).then((results) => {
      if (!canceled) setLookupError(results.some((result) => result.status === 'rejected'));
    });
    return () => { canceled = true; };
  }, []);

  useEffect(() => {
    const values = Object.fromEntries(Object.entries(textInputs).map(([key, value]) => [key, value.trim()]));
    if (Object.keys(values).every((key) => filters[key] === values[key])) return;
    const timer = setTimeout(() => {
      setFilters((prev) => ({ ...prev, ...values }));
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [textInputs, filters]);

  const invalidRange = filters.date_from && filters.date_to && filters.date_to < filters.date_from;
  const invalidCall = textInputs.call_id !== '' && !/^[1-9]\d*$/.test(textInputs.call_id.trim());
  const invalidFilters = invalidRange || invalidCall;

  const agentById = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);
  const agentLabel = useCallback(
    (id) => {
      if (id === null || id === undefined) return '—';
      const a = agentById.get(id);
      return a ? a.name : `#${id}`;
    },
    [agentById]
  );

  const navigate = useNavigate();

  const [stats, setStats] = useState(null);

  const fetchStats = useCallback(() => {
    const currentRequest = ++statsRequestId.current;
    callsApi
      .statsSummary()
      .then((data) => { if (currentRequest === statsRequestId.current) setStats(data); })
      .catch(() => undefined);
  }, []);

  // `keepRows` re-reads without emptying the table first — a refresh of what is
  // already on screen should not flash it away and back.
  // `background` is the silent auto-refresh: no spinner, no error banner, rows
  // are only swapped when the answer arrives. Responses of superseded requests
  // (a filter/page changed meanwhile) are dropped via the sequence number.
  const callsSeq = useRef(0);
  const fetchCalls = useCallback(
    ({ keepRows = false, background = false } = {}) => {
      const seq = ++callsSeq.current;
      if (invalidFilters) {
        if (!background) setRefreshing(false);
        return undefined;
      }
      if (!keepRows && !background) setRows(null);
      if (!background) {
        setRefreshing(true);
        setLoadError(null);
      }
      return callsApi
        .list({ ...historyDateQuery(filters, !fullAccess), limit: pageSize, offset })
        .then((res) => {
          if (seq !== callsSeq.current) return;
          setRows(Array.isArray(res?.data) ? res.data : []);
          setTotal(res?.count ?? 0);
          if (background) setLoadError(null);
        })
        .catch((e) => {
          if (seq !== callsSeq.current || background) return;
          setLoadError(e.message);
          setRows([]);
          setTotal(0);
        })
        .finally(() => {
          if (!background && seq === callsSeq.current) setRefreshing(false);
        });
    },
    [filters, offset, pageSize, invalidFilters, fullAccess]
  );

  const changePageSize = (size) => {
    setOffset(0);
    setPageSize(size);
  };

  useEffect(() => {
    fetchCalls();
    return () => { callsSeq.current += 1; };
  }, [fetchCalls]);

  useEffect(() => {
    fetchStats();
    return () => { statsRequestId.current += 1; };
  }, [fetchStats]);

  const reload = () => {
    fetchCalls({ keepRows: true });
    fetchStats();
  };

  // Live updates: re-read the table (and the stats strip) every 10 s without
  // touching loading state, scroll, filters or the page. Paused while any
  // modal is open (the open call refreshes itself below).
  useAutoRefresh(
    () => Promise.all([fetchCalls({ background: true }), fetchStats()]),
    { paused: Boolean(detail || originate || confirmCancel) }
  );

  // The open call: keep it in step with the backend while it can still change
  // (pending/calling, or a settled call whose analysis is still landing).
  const detailData = detail?.data;
  const detailLive =
    Boolean(detailData) &&
    (ACTIVE_CALL_STATUSES.includes(detailData.status) ||
      (detailData.status === 'completed' && !detailData.outcome));
  const detailId = detail?.id;
  useAutoRefresh(
    () =>
      callsApi.get(detailId).then((data) => {
        setDetail((prev) => (prev && prev.id === detailId ? { id: detailId, data } : prev));
      }),
    { enabled: detailLive, paused: confirmCancel || originate }
  );

  // A changed filter always returns to the first page.
  const setFilter = (key, value) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const toggleSort = (col) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, sort: prev.sort === col ? `-${col}` : col }));
  };

  const sortIndicator = (col) => {
    if (filters.sort === col) return ' ↑';
    if (filters.sort === `-${col}`) return ' ↓';
    return '';
  };

  const resetFilters = () => {
    setOffset(0);
    setTextInputs(EMPTY_TEXT);
    setFilters(EMPTY_FILTERS);
  };

  const removeFilter = (key) => {
    if (Object.hasOwn(EMPTY_TEXT, key)) setTextInputs((prev) => ({ ...prev, [key]: '' }));
    setFilter(key, '');
  };
  const setPeriod = (period) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, ...periodRange(period, !fullAccess) }));
  };
  const activePeriod = PERIODS.find((period) => {
    const range = periodRange(period, !fullAccess);
    return range.date_from === filters.date_from && range.date_to === filters.date_to;
  });

  const openDetail = async (id) => {
    setDetail({ id });
    try {
      const data = await callsApi.get(id);
      setDetail((prev) => prev?.id === id ? { id, data } : prev);
    } catch (e) {
      setDetail((prev) => prev?.id === id ? { id, error: e.message } : prev);
    }
  };

  const openOriginate = () => {
    setFormValues(buildInitialValues(originateFields(agents, canAssign), null));
    setFormErrors({});
    setOriginate(true);
  };

  const submitOriginate = async () => {
    const fields = originateFields(agents, canAssign);
    const { payload, errors } = buildPayload(fields, formValues);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setOriginating(true);
    try {
      const created = await callsApi.originate(payload);
      toast(t('calls.originated', { id: created.id }), 'success');
      setOriginate(false);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setOriginating(false);
    }
  };

  // Cancel the call open in the detail modal, then re-read it (it comes back
  // `canceled`) and refresh the list so the row's status follows.
  const doCancel = async () => {
    if (!detail?.id) return;
    setCancelBusy(true);
    try {
      await callsApi.cancel(detail.id);
      toast(t('calls.cancel.done'), 'success');
      setConfirmCancel(false);
      const data = await callsApi.get(detail.id);
      setDetail({ id: detail.id, data });
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setCancelBusy(false);
    }
  };

  // After a tags save (PUT /calls/{id}/tags returns the updated SCallRead):
  // refresh the open detail modal in place and the list behind it, so the new
  // chips show up in both without a manual reload.
  const handleTagsUpdated = (updated) => {
    setDetail((prev) => (prev && prev.id === updated.id ? { id: prev.id, data: { ...prev.data, ...updated } } : prev));
    reload();
  };

  // Pending is always cancelable; calling only while its latest attempt has
  // not started dialing yet — matches CallCRUD.cancel's own guard.
  const canCancel = Boolean(
    detail?.data &&
      (CANCELABLE_STATUSES.has(detail.data.status) ||
        (detail.data.status === 'calling' &&
          detail.data.attempts?.at(-1)?.status === 'queued'))
  );

  const activeFilters = Object.entries(filters).filter(([key, value]) => key !== 'sort' && value !== '');
  const filtersDirty = activeFilters.length > 0 || Object.values(textInputs).some(Boolean) || filters.sort !== EMPTY_FILTERS.sort;
  const advancedCount = ['campaign_id', 'attempt_status', 'outcome', 'reason_category', 'sentiment', 'direction', 'from_search', 'language', 'has_recording', 'call_id'].filter((key) => filters[key]).length;
  const filterValue = (key, value) => {
    if (key === 'date_from' || key === 'date_to') return value.replace('T', ' ');
    if (key === 'agent_id') return agentLabel(Number(value));
    if (key === 'campaign_id') return campaigns.find((campaign) => String(campaign.id) === value)?.name || `#${value}`;
    const namespace = { status: 'statuses', outcome: 'outcomes', reason_category: 'reasonCategories', sentiment: 'sentiments', direction: 'directions', has_recording: 'recordings' }[key];
    return namespace ? t(`calls.${namespace}.${value}`) : value;
  };

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('calls.title')}</PageTitle>
        <HeaderActions>
          {canManage && (
            <PrimaryButton theme={theme} type="button" onClick={openOriginate}>
              + {t('calls.originate')}
            </PrimaryButton>
          )}
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        {stats && <FilterNote theme={theme} as="p">{t('calls.stats.scope')}</FilterNote>}
        {stats && (
          <StatsGrid>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.total')}</StatLabel>
              <StatValue theme={theme}>{stats.total ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.pending')}</StatLabel>
              <StatValue theme={theme} $color="#2563eb">{stats.statuses?.pending ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.calling')}</StatLabel>
              <StatValue theme={theme} $color="#7c3aed">{stats.statuses?.calling ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.completed')}</StatLabel>
              <StatValue theme={theme} $color="#16a34a">{stats.statuses?.completed ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.exhausted')}</StatLabel>
              <StatValue theme={theme} $color="#dc2626">{stats.statuses?.exhausted ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.answeringMachine')}</StatLabel>
              <StatValue theme={theme} $color="#d97706">{stats.outcomes?.answerphone ?? stats.outcomes?.answering_machine ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.escalated')}</StatLabel>
              <StatValue theme={theme} $color="#7c3aed">{stats.outcomes?.escalated ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.smsSent')}</StatLabel>
              <StatValue theme={theme} $color="#2563eb">{stats.outcomes?.sms_sent ?? 0}</StatValue>
            </StatCard>
            <StatCard theme={theme}>
              <StatLabel theme={theme}>{t('calls.stats.noAnswer')}</StatLabel>
              <StatValue theme={theme} $color="#6b7280">{stats.outcomes?.no_answer ?? 0}</StatValue>
            </StatCard>
          </StatsGrid>
        )}

        <FilterCard theme={theme}>
          <FilterHeader theme={theme}>
            <h3><HiAdjustmentsHorizontal />{t('calls.filters.title')}</h3>
            <HeaderActions>
              <HistoryExport
                name="calls"
                disabled={Boolean(invalidFilters) || refreshing || Boolean(loadError)}
                empty={total === 0}
                onExport={(format) => callsApi.export(historyDateQuery(filters, !fullAccess), format)}
              />
              {filtersDirty && <SecondaryButton theme={theme} type="button" onClick={resetFilters}>{t('calls.filters.reset')}</SecondaryButton>}
              <RefreshButton theme={theme} type="button" $busy={refreshing} disabled={refreshing || Boolean(invalidFilters)} onClick={reload} title={t('calls.filters.refresh')} aria-label={t('calls.filters.refresh')}>
                <HiArrowPath />
              </RefreshButton>
            </HeaderActions>
          </FilterHeader>
          <PeriodBar>
            {PERIODS.map((period) => <PeriodButton key={period} type="button" theme={theme} $active={activePeriod === period} aria-pressed={activePeriod === period} onClick={() => setPeriod(period)}>{t(`sms.periods.${period}`)}</PeriodButton>)}
            <FilterNote theme={theme}>{t(fullAccess ? 'calls.filters.dateHint' : 'calls.filters.dateTimeHint')}</FilterNote>
          </PeriodBar>
          <FilterGrid>
            <SearchFilter theme={theme}>
              {t('calls.filters.search')}
              <TextInput theme={theme} type="search" value={textInputs.search} maxLength={1600} placeholder={t('calls.filters.searchPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, search: e.target.value }))} />
            </SearchFilter>
            <Filter theme={theme}>
              {t('calls.filters.client_search')}
              <TextInput theme={theme} type="search" value={textInputs.client_search} maxLength={128} placeholder={t('calls.filters.clientPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, client_search: e.target.value }))} />
            </Filter>
            <Filter theme={theme}>
              {t('calls.filters.agent_id')}
              <Select theme={theme} value={filters.agent_id} onChange={(e) => setFilter('agent_id', e.target.value)}>
                <option value="">{t('calls.filters.all')}</option>
                {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} (#{agent.id})</option>)}
              </Select>
            </Filter>
            <StatusFilter theme={theme}>
              {t('calls.filters.status')}
              <Select theme={theme} value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
                <option value="">{t('calls.filters.all')}</option>
                {STATUSES.map((status) => <option key={status} value={status}>{t(`calls.statuses.${status}`)}</option>)}
              </Select>
            </StatusFilter>
            <Filter theme={theme}>
              {t('calls.filters.date_from')}
              <TextInput theme={theme} type={fullAccess ? "date" : "datetime-local"} value={filters.date_from} max={filters.date_to || undefined} aria-invalid={Boolean(invalidRange)} onChange={(e) => setFilter('date_from', e.target.value)} />
            </Filter>
            <Filter theme={theme}>
              {t('calls.filters.date_to')}
              <TextInput theme={theme} type={fullAccess ? "date" : "datetime-local"} value={filters.date_to} min={filters.date_from || undefined} aria-invalid={Boolean(invalidRange)} onChange={(e) => setFilter('date_to', e.target.value)} />
            </Filter>
          </FilterGrid>
          <AdvancedToggle theme={theme} type="button" $open={advanced} aria-expanded={advanced} aria-controls="calls-advanced-filters" onClick={() => setAdvanced((prev) => !prev)}>
            {t('calls.filters.advanced')}{advancedCount > 0 && ` (${advancedCount})`} <HiChevronDown />
          </AdvancedToggle>
          {advanced && <AdvancedGrid theme={theme} id="calls-advanced-filters">
            <Filter theme={theme}>
              {t('calls.filters.campaign_id')}
              <Select theme={theme} value={filters.campaign_id} onChange={(e) => setFilter('campaign_id', e.target.value)}>
                <option value="">{t('calls.filters.all')}</option>
                {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name} (#{campaign.id})</option>)}
              </Select>
            </Filter>
            <Filter theme={theme}>
              {t('calls.filters.attempt_status')}
              <Select theme={theme} value={filters.attempt_status} onChange={(e) => setFilter('attempt_status', e.target.value)}>
                <option value="">{t('calls.filters.all')}</option>
                {statusOptions(t, KINDS.ATTEMPT).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            </Filter>
            {[
              ['outcome', OUTCOMES, 'outcomes'],
              ['reason_category', REASON_CATEGORIES, 'reasonCategories'],
              ['sentiment', ['positive', 'neutral', 'negative'], 'sentiments'],
              ['direction', ['outbound', 'inbound'], 'directions'],
              ['has_recording', ['true', 'false'], 'recordings'],
            ].filter(([key]) => fullAccess || key !== 'direction').map(([key, options, namespace]) => <Filter key={key} theme={theme}>
              {t(`calls.filters.${key}`)}
              <Select theme={theme} value={filters[key]} onChange={(e) => setFilter(key, e.target.value)}>
                <option value="">{t('calls.filters.all')}</option>
                {options.map((value) => <option key={value} value={value}>{t(`calls.${namespace}.${value}`)}</option>)}
              </Select>
            </Filter>)}
            {fullAccess && <Filter theme={theme}>
              {t('calls.filters.from_search')}
              <TextInput theme={theme} type="search" value={textInputs.from_search} maxLength={128} placeholder={t('calls.filters.numberPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, from_search: e.target.value }))} />
            </Filter>}
            <Filter theme={theme}>
              {t('calls.filters.language')}
              <TextInput theme={theme} value={textInputs.language} maxLength={32} placeholder={t('calls.filters.languagePlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, language: e.target.value }))} />
            </Filter>
            <Filter theme={theme}>
              {t('calls.filters.call_id')}
              <TextInput theme={theme} type="text" inputMode="numeric" pattern="[0-9]*" value={textInputs.call_id} aria-invalid={invalidCall} placeholder={t('calls.filters.callPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, call_id: e.target.value }))} />
            </Filter>
          </AdvancedGrid>}
          {lookupError && <EmptyStateText theme={theme} role="status">{t('calls.filters.lookupError')}</EmptyStateText>}
          {activeFilters.length > 0 && <Chips>
            {activeFilters.map(([key, value]) => <Chip key={key} type="button" theme={theme} onClick={() => removeFilter(key)} aria-label={t('calls.filters.remove', { filter: t(`calls.filters.${key}`) })} title={`${t(`calls.filters.${key}`)}: ${filterValue(key, value)}`}>
              <span>{t(`calls.filters.${key}`)}: {filterValue(key, value)}</span><HiXMark />
            </Chip>)}
          </Chips>}
        </FilterCard>
        <ResultsBar theme={theme}>
          <span role="status" aria-live="polite">{t('calls.results', { count: invalidFilters || refreshing || loadError ? '—' : new Intl.NumberFormat(locale).format(total) })}</span>
          <label>{t('calls.filters.sort')}
            <Select theme={theme} value={filters.sort} onChange={(e) => setFilter('sort', e.target.value)}>
              {SORTS.map((sort) => <option key={sort} value={sort}>{t(`calls.sorts.${sort}`)}</option>)}
            </Select>
          </label>
        </ResultsBar>

        {invalidFilters ? (
          <EmptyState theme={theme}><EmptyStateText theme={theme} role="alert">{t(invalidRange ? 'calls.filters.invalidRange' : 'calls.filters.invalidCall')}</EmptyStateText></EmptyState>
        ) : rows === null ? (
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
        ) : loadError ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{loadError}</EmptyStateText>
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.noData')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{t('calls.empty')}</EmptyStateText>
          </EmptyState>
        ) : (
          <>
            <TableContainer theme={theme}>
              <Table>
                <TableHeader theme={theme}>
                  <tr>
                    <TableHeaderCell theme={theme}>{t('common.id')}</TableHeaderCell>
                    <SortableHeader theme={theme} onClick={() => toggleSort('status')}>
                      {t('common.status')}{sortIndicator('status')}
                    </SortableHeader>
                    <TableHeaderCell theme={theme}>{t('calls.columns.outcome')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('calls.columns.agent')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('calls.columns.to')}</TableHeaderCell>
                    {fullAccess && <TableHeaderCell theme={theme}>{t('calls.columns.from')}</TableHeaderCell>}
                    <TableHeaderCell theme={theme} $align="center">
                      {t('calls.columns.language')}
                    </TableHeaderCell>
                    <SortableHeader theme={theme} $align="right" onClick={() => toggleSort('duration')}>
                      {t('calls.columns.duration')}{sortIndicator('duration')}
                    </SortableHeader>
                    <SortableHeader theme={theme} onClick={() => toggleSort('created_at')}>
                      {t('calls.columns.created')}{sortIndicator('created_at')}
                    </SortableHeader>
                    <TableHeaderCell theme={theme}>{t('calls.columns.tags')}</TableHeaderCell>
                  </tr>
                </TableHeader>
                <tbody>
                  {rows.map((row) => (
                    <TableRow
                      key={row.id}
                      theme={theme}
                      onClick={() => openDetail(row.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <TableCell theme={theme}>{row.id}</TableCell>
                      <TableCell theme={theme}>
                        <StatusBadge kind={KINDS.CALL} value={row.status} />
                      </TableCell>
                      <TableCell theme={theme}>
                        {row.outcome ? <StatusBadge kind={KINDS.OUTCOME} value={row.outcome} /> : '—'}
                      </TableCell>
                      <TableCell theme={theme}>{agentLabel(row.agent_id)}</TableCell>
                      <TableCell theme={theme}>{row.client?.phone ?? '—'}</TableCell>
                      {fullAccess && <TableCell theme={theme}>{row.from_number ?? '—'}</TableCell>}
                      <TableCell theme={theme} $align="center">
                        {row.language ?? '—'}
                      </TableCell>
                      <TableCell theme={theme} $align="right">
                        {row.duration_seconds ?? '—'}
                      </TableCell>
                      <TableCell theme={theme}>{formatDateTime(row.created_at)}</TableCell>
                      <TableCell theme={theme}>
                        {Array.isArray(row.tags) && row.tags.length > 0 ? (
                          <TagsRow>
                            {row.tags.map((tag) => (
                              <Badge key={tag} $color="#7c3aed">
                                {callTagLabel(t, tag)}
                              </Badge>
                            ))}
                          </TagsRow>
                        ) : (
                          '—'
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </tbody>
              </Table>
            </TableContainer>

            <Pagination
              offset={offset}
              limit={pageSize}
              total={total}
              disabled={refreshing}
              onChange={setOffset}
              pageSize={pageSize}
              onPageSizeChange={changePageSize}
            />
          </>
        )}
      </ContentScroll>

      {detail && (
        <Modal
          title={t('calls.detail.title', { id: detail.id })}
          onClose={() => setDetail(null)}
          wide
          footer={
            canCancel && canManage ? (
              <DangerButton
                theme={theme}
                type="button"
                disabled={cancelBusy}
                onClick={() => setConfirmCancel(true)}
              >
                {t('calls.cancel.action')}
              </DangerButton>
            ) : undefined
          }
        >
          {detail.error ? (
            <EmptyStateText theme={theme}>{detail.error}</EmptyStateText>
          ) : !detail.data ? (
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
          ) : (
            <CallDetail
              data={detail.data}
              theme={theme}
              t={t}
              agentLabel={agentLabel}
              onTagsUpdated={handleTagsUpdated}
              onGoToLead={(client) => navigate(`/audiences?search=${encodeURIComponent(client.phone)}`)}
              canManage={canManage}
              showFrom={fullAccess}
            />
          )}
        </Modal>
      )}

      {confirmCancel && detail && (
        <Modal
          title={t('calls.cancel.title', { id: detail.id })}
          onClose={() => !cancelBusy && setConfirmCancel(false)}
          footer={
            <>
              <SecondaryButton
                theme={theme}
                type="button"
                disabled={cancelBusy}
                onClick={() => setConfirmCancel(false)}
              >
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton theme={theme} type="button" disabled={cancelBusy} onClick={doCancel}>
                {cancelBusy ? t('calls.cancel.canceling') : t('calls.cancel.confirm')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>{t('calls.cancel.body')}</EmptyStateText>
        </Modal>
      )}

      {originate && (
        <Modal
          title={t('calls.originateTitle')}
          onClose={() => setOriginate(false)}
          wide
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setOriginate(false)}>
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton theme={theme} type="button" disabled={originating} onClick={submitOriginate}>
                {originating ? t('common.saving') : t('calls.originate')}
              </PrimaryButton>
            </>
          }
        >
          <ResourceForm
            fields={originateFields(agents, canAssign)}
            values={formValues}
            errors={formErrors}
            onChange={setFormValues}
          />
        </Modal>
      )}
    </PageContent>
  );
};

// A call is *who to reach and with what*; each attempt is one dial-to-hangup
// leg with its own status, transcript and outcome — a retry is a new attempt
// row, never an overwrite. SCallDetailsRead nests them as `attempts`.
// Module-level (not declared inside CallDetail): the open call re-renders every
// auto-refresh, and a component created per render would remount its subtree.
const Field = ({ label, children }) => {
  const { theme } = useTheme();
  return (
    <>
      <DetailKey theme={theme}>{label}</DetailKey>
      <DetailValue theme={theme}>{children}</DetailValue>
    </>
  );
};

const CallDetail = ({ data, theme, t, agentLabel, onTagsUpdated, onGoToLead, canManage, showFrom }) => {
  const attempts = Array.isArray(data.attempts) ? data.attempts : [];
  const hasBonuses = Array.isArray(data.bonuses) && data.bonuses.length > 0;
  const hasAttributes = data.attributes && Object.keys(data.attributes).length > 0;
  const hasPlayerFields =
    data.player_id || data.vip_status || data.last_deposit != null || data.last_active || data.country || data.timezone;

  // `uuid` is admin-only (VOAD-28) — the backend blanks it to null for a
  // non-admin-ish caller, so it must not be assumed present.
  const hasUuid = data.uuid !== null && data.uuid !== undefined;

  const [tagsState, setTagsState] = useState(() => parseCallTags(data.tags));
  const [tagsBusy, setTagsBusy] = useState(false);
  const [tagsError, setTagsError] = useState(null);

  // Re-sync the editor whenever a different call (or a freshly saved one) is
  // shown — `data.tags` is the source of truth, the editor is just a draft of it.
  // Keyed on the tags' content, not the array identity: the auto-refresh
  // hands over a fresh array every 10 s, which must not wipe an unsaved draft.
  const tagsKey = JSON.stringify(data.tags ?? []);
  useEffect(() => {
    setTagsState(parseCallTags(data.tags));
    setTagsError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.id, tagsKey]);

  const toggleSimpleTag = (tag) => {
    setTagsState((prev) => ({
      ...prev,
      simple: prev.simple.includes(tag) ? prev.simple.filter((x) => x !== tag) : [...prev.simple, tag],
    }));
  };

  const toggleFinishedTag = () => {
    setTagsState((prev) => ({ ...prev, finished: !prev.finished }));
  };

  const saveTags = async () => {
    const tags = [...tagsState.simple];
    if (tagsState.finished) {
      const suffix = tagsState.finishedResult.trim();
      tags.push(suffix ? `${CALL_TAG_FINISHED}: ${suffix}` : CALL_TAG_FINISHED);
    }
    setTagsBusy(true);
    setTagsError(null);
    try {
      const updated = await callsApi.updateTags(data.id, tags);
      toast(t('common.saved'), 'success');
      onTagsUpdated?.(updated);
    } catch (e) {
      setTagsError(e.message);
    } finally {
      setTagsBusy(false);
    }
  };

  return (
    <>
      <DetailGrid>
        <Field label={t('calls.detail.status')}>
          <StatusBadge kind={KINDS.CALL} value={data.status} />
        </Field>
        {data.outcome && (
          <Field label={t('calls.detail.outcome')}>
            <StatusBadge kind={KINDS.OUTCOME} value={data.outcome} />
          </Field>
        )}
        {data.reason_category && (
          <Field label={t('calls.detail.reasonCategory')}>
            {t(`calls.reasonCategories.${data.reason_category}`) || String(data.reason_category).replace(/_/g, ' ')}
          </Field>
        )}
        {data.selected_offer && (
          <Field label={t('calls.detail.selectedOffer')}>{data.selected_offer}</Field>
        )}
        <Field label={t('calls.detail.agent')}>{agentLabel(data.agent_id)}</Field>
        <Field label={t('calls.detail.to')}>
          {data.client?.phone ?? '—'}
          {data.client && (
            <LeadLink theme={theme} type="button" onClick={() => onGoToLead(data.client)}>
              {t('calls.detail.goToLead')}
            </LeadLink>
          )}
        </Field>
        {showFrom && <Field label={t('calls.detail.from')}>{data.from_number ?? '—'}</Field>}
        <Field label={t('calls.detail.language')}>{data.language ?? '—'}</Field>
        <Field label={t('calls.detail.duration')}>{data.duration_seconds ?? '—'}</Field>
        <Field
          label={
            <>
              {t('calls.detail.attemptsMade')}
              <InfoIcon title={t('calls.detail.attemptsMadeHint')} />
            </>
          }
        >
          {data.attempts_made}
        </Field>
        {data.next_attempt_at && (
          <Field label={t('calls.detail.nextAttempt')}>
            {formatDateTime(data.next_attempt_at)}
            {data.is_callback && (
              <Badge $color="#d97706" style={{ marginLeft: 8 }}>
                {t('calls.detail.callbackTag')}
              </Badge>
            )}
          </Field>
        )}
        <Field label={t('calls.detail.created')}>{formatDateTime(data.created_at)}</Field>
        {hasUuid && <Field label={t('calls.detail.uuid')}>{data.uuid}</Field>}
      </DetailGrid>

      <Section>
        <SectionLabel theme={theme}>{t('calls.detail.tags')}</SectionLabel>
        {data.tags?.length > 0 ? (
          <TagsRow style={{ marginBottom: 10 }}>
            {data.tags.map((tag) => (
              <Badge key={tag} $color="#7c3aed">
                {callTagLabel(t, tag)}
              </Badge>
            ))}
          </TagsRow>
        ) : (
          <EmptyStateText theme={theme}>—</EmptyStateText>
        )}

        {canManage && (
          <>
            <TagsEditor theme={theme}>
              {SIMPLE_CALL_TAGS.map((tag) => (
                <label key={tag}>
                  <input
                    type="checkbox"
                    checked={tagsState.simple.includes(tag)}
                    onChange={() => toggleSimpleTag(tag)}
                  />
                  {callTagLabel(t, tag)}
                </label>
              ))}
              <label>
                <input type="checkbox" checked={tagsState.finished} onChange={toggleFinishedTag} />
                {callTagLabel(t, CALL_TAG_FINISHED)}
              </label>
              {tagsState.finished && (
                <input
                  type="text"
                  placeholder={t('calls.detail.tagResultPlaceholder')}
                  value={tagsState.finishedResult}
                  onChange={(e) =>
                    setTagsState((prev) => ({ ...prev, finishedResult: e.target.value }))
                  }
                />
              )}
            </TagsEditor>

            {tagsError && (
              <DetailValue theme={theme} style={{ color: '#dc2626', marginBottom: 8 }}>
                {tagsError}
              </DetailValue>
            )}

            <SecondaryButton theme={theme} type="button" disabled={tagsBusy} onClick={saveTags}>
              {tagsBusy ? t('common.saving') : t('common.save')}
            </SecondaryButton>
          </>
        )}
      </Section>

      {hasPlayerFields && (
        <Section>
          <SectionLabel theme={theme}>{t('calls.detail.player')}</SectionLabel>
          <DetailGrid>
            {data.player_id && <Field label={t('calls.detail.playerId')}>{data.player_id}</Field>}
            {data.vip_status && <Field label={t('calls.detail.vipStatus')}>{data.vip_status}</Field>}
            {data.last_deposit != null && (
              <Field label={t('calls.detail.lastDeposit')}>{data.last_deposit}</Field>
            )}
            {data.last_active && (
              <Field label={t('calls.detail.lastActive')}>{formatDateTime(data.last_active)}</Field>
            )}
            {data.country && <Field label={t('calls.detail.country')}>{data.country}</Field>}
            {data.timezone && <Field label={t('calls.detail.timezone')}>{data.timezone}</Field>}
          </DetailGrid>
        </Section>
      )}

      {(hasBonuses || hasAttributes) && (
        <Section>
          <SectionLabel theme={theme}>
            {t('calls.detail.customer')} <span>{t('calls.detail.customerHint')}</span>
          </SectionLabel>
          {hasBonuses && <JsonView value={data.bonuses} maxHeight="150px" />}
          {hasAttributes && <JsonView value={data.attributes} maxHeight="150px" />}
        </Section>
      )}

      {data.overrides && (
        <Section>
          <SectionLabel theme={theme}>
            {t('calls.detail.overrides')} <span>{t('calls.detail.overridesHint')}</span>
          </SectionLabel>
          <JsonView value={data.overrides} maxHeight="200px" />
        </Section>
      )}

      <Section>
        <SectionLabel theme={theme}>{t('calls.detail.attempts')}</SectionLabel>
        {attempts.length === 0 ? (
          <EmptyStateText theme={theme}>{t('calls.detail.noAttempts')}</EmptyStateText>
        ) : (
          attempts.map((attempt) => (
            <AttemptDetail key={attempt.id} attempt={attempt} callId={data.id} theme={theme} t={t} />
          ))
        )}
      </Section>
    </>
  );
};

const AttemptCard = styled.div`
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 12px;
`;

const AttemptHeader = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.primary};
`;

// Secondary line under the header: when the attempt happened and, when it
// connected, how the conversation's own timing broke down. Kept separate from
// AttemptHeader (status/outcome/offer) so a screen full of 10+ attempts still
// scans as "one glance per row" instead of one long wrapped line of mixed
// facts.
const AttemptMeta = styled.div`
  margin-bottom: 8px;
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const AttemptDetail = ({ attempt, callId, theme, t }) => {
  // VOAD-58: no raw JSON, no system prompt — see utils/transcript.
  const messages = useMemo(() => normalizeMessages(attempt.messages, t), [attempt.messages, t]);
  // Never answered => no audio was ever captured and no conversation ever
  // happened — both the recording and transcript sections skip straight to
  // their empty states rather than firing a request that can only 404.
  const connected = Boolean(attempt.answered_at);

  return (
    <AttemptCard theme={theme}>
      <AttemptHeader theme={theme}>
        <strong>{t('calls.detail.attempt', { seq: attempt.seq })}</strong>
        <StatusBadge kind={KINDS.ATTEMPT} value={attempt.status} />
        {attempt.outcome && <StatusBadge kind={KINDS.OUTCOME} value={attempt.outcome} />}
        {attempt.selected_offer && <span>{attempt.selected_offer}</span>}
      </AttemptHeader>

      <AttemptMeta theme={theme}>
        {t('calls.detail.attemptStarted')}: {formatDateTime(attempt.created_at)}
        {connected ? (
          <>
            {' · '}
            {t('calls.detail.attemptTalkTime')}: {formatDateTime(attempt.answered_at)} →{' '}
            {formatDateTime(attempt.ended_at)}
            {attempt.duration_seconds != null &&
              ` (${t('calls.detail.attemptDuration', { seconds: attempt.duration_seconds })})`}
          </>
        ) : (
          <>{' · '}{t('calls.detail.attemptNotAnswered')}</>
        )}
      </AttemptMeta>

      {attempt.summary && <DetailValue theme={theme}>{attempt.summary}</DetailValue>}
      {attempt.error && (
        <DetailValue theme={theme} style={{ color: '#dc2626' }}>
          {attempt.error}
        </DetailValue>
      )}

      <Section>
        <SectionLabel theme={theme}>{t('calls.detail.recording')}</SectionLabel>
        <RecordingSection callId={callId} attempt={attempt} connected={connected} theme={theme} t={t} />
      </Section>

      <Section style={{ marginBottom: 0 }}>
        <SectionLabel theme={theme}>{t('calls.detail.transcript')}</SectionLabel>
        {!connected || messages.length === 0 ? (
          <EmptyStateText theme={theme}>{t('calls.detail.noMessages')}</EmptyStateText>
        ) : (
          <Bubbles>
            {messages.map((msg) => (
              <Bubble key={msg.key} theme={theme} $role={msg.role}>
                <BubbleRole theme={theme}>{roleLabel(msg.role, t)}</BubbleRole>
                {msg.text}
              </Bubble>
            ))}
          </Bubbles>
        )}
      </Section>
    </AttemptCard>
  );
};

// Fetches the attempt's recording pointer (VOAD-37) lazily, per attempt, and
// renders the player once it resolves. A 404 — attempt never answered, or
// answered but nothing stored — is the expected common case today (no call
// engine deployment captures audio yet) and renders the same clean "no
// recording available" text as any other miss, never an error toast; a
// non-404 failure (e.g. a 403 for a non-admin viewer, out of this task's
// scope to gate in the UI) falls back to the same neutral message rather
// than surfacing a scary/technical error for what a viewer would otherwise
// read as "no player showed up".
const RecordingSection = ({ callId, attempt, connected, theme, t }) => {
  const [state, setState] = useState({ status: 'idle' });

  useEffect(() => {
    if (!connected) {
      setState({ status: 'unavailable' });
      return undefined;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    callsApi
      .getRecording(callId, attempt.id)
      .then((res) => {
        if (cancelled) return;
        if (res?.recording_url) {
          setState({ status: 'ready', url: res.recording_url });
        } else {
          setState({ status: 'unavailable' });
        }
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'unavailable' });
      });
    return () => {
      cancelled = true;
    };
  }, [callId, attempt.id, connected]);

  if (state.status === 'ready') return <CallRecordingPlayer recordingUrl={state.url} />;
  if (state.status === 'loading') return <EmptyStateText theme={theme}>{t('calls.detail.recordingLoading')}</EmptyStateText>;
  return <EmptyStateText theme={theme}>{t('calls.detail.recordingUnavailable')}</EmptyStateText>;
};
