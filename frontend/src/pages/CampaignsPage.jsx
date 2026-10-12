import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import styled, { keyframes } from 'styled-components';
import { HiArrowPath } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { CampaignStatusBadge } from 'components/badges';
import { KINDS, statusValues, statusLabel } from 'utils/statusMap';
import { useAutoRefresh } from 'utils/useAutoRefresh';
import { Modal } from 'components/Modal';
import { Pagination } from 'components/Pagination';
import { toast } from 'components/Toaster';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  Select,
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
  UploadArea,
  ResultTable,
  TextInput,
  CheckboxLabel,
  formatDateTime,
} from 'components/ui';
import { campaignsApi, agentsApi, audiencesApi, MAX_PAGE } from 'utils/callApi';
import { parseContactsInput } from 'utils/parseContactsInput';
import { campaignScheduleFields } from 'pages/campaignFields';
import { useUser } from 'contexts/UserContext';
import { canWrite } from 'utils/permissions';

// Status values/labels/colours: utils/statusMap.js (campaign kind).
// Which lifecycle action is available from which status — mirrors
// CampaignService.start/pause/complete's own refusals, so the buttons that
// would 422 are simply not offered. `markError` (POST /campaigns/{id}/error,
// VOAD-36) is offered from every non-terminal status, same as the other
// operator-triggered actions here.
const NEXT_ACTIONS = {
  draft: ['start', 'markError'],
  scheduled: ['start', 'pause', 'markError'],
  running: ['pause', 'complete', 'markError'],
  paused: ['start', 'complete', 'markError'],
  completed: ['restart'],
  error: ['start', 'restart'],
};
// A breakdown shown in the detail modal — read from GET /campaigns/{id}/counters.

// Sort control options wired to GET /campaigns's `sort` param (VOAD-36):
// name|created_at|starts_at|status, optionally '-'-prefixed for descending.
// '' (default) omits the param and keeps the backend's own default (-id,
// newest first).
const SORT_OPTIONS = [
  { value: '', labelKey: 'campaigns.filters.sortOptions.default' },
  { value: 'name', labelKey: 'campaigns.filters.sortOptions.nameAsc' },
  { value: '-name', labelKey: 'campaigns.filters.sortOptions.nameDesc' },
  { value: 'created_at', labelKey: 'campaigns.filters.sortOptions.createdAsc' },
  { value: '-created_at', labelKey: 'campaigns.filters.sortOptions.createdDesc' },
  { value: 'starts_at', labelKey: 'campaigns.filters.sortOptions.startsAsc' },
  { value: '-starts_at', labelKey: 'campaigns.filters.sortOptions.startsDesc' },
  { value: 'status', labelKey: 'campaigns.filters.sortOptions.statusAsc' },
  { value: '-status', labelKey: 'campaigns.filters.sortOptions.statusDesc' },
];

// The date-range filter exposes `created_from`/`created_to` only (not
// starts_at, which the backend also accepts) — created_at is never null,
// while starts_at is for a campaign that runs "as soon as started", so a
// created-date range answers "what was added in this window" without a
// blank column skewing results. starts_at can still be sorted on above.
const EMPTY_FILTERS = {
  status: [],
  agent_id: '',
  search: '',
  created_from: '',
  created_to: '',
  include_archived: false,
  sort: '',
};

const DEFAULT_PAGE_SIZE = 50;

const FiltersBar = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px 12px;
  margin-bottom: 16px;
`;

const Filter = styled.label`
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  text-transform: uppercase;
  letter-spacing: 0.04em;

  select {
    min-width: 170px;
  }
`;

// Status is a multi-select (the backend takes repeatable ?status=, VOAD-36),
// rendered as toggle chips rather than a <select multiple> for discoverability.
const StatusChips = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 360px;
`;

const StatusChip = styled.button`
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 999px;
  border: 1px solid ${({ theme, $active }) => ($active ? theme.colors.accentNeon : theme.colors.border)};
  background: transparent;
  color: ${({ theme, $active }) => ($active ? theme.colors.accentNeon : theme.colors.secondary)};
  font-weight: ${({ $active }) => ($active ? 700 : 500)};
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease;
`;

const spin = keyframes`
  to { transform: rotate(360deg); }
`;

const RefreshButton = styled(SecondaryButton)`
  padding: 8px 10px;
  font-size: 16px;

  svg {
    animation: ${({ $busy }) => ($busy ? spin : 'none')} 0.8s linear infinite;
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
  white-space: pre-wrap;
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

const CounterRow = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: 10px;
`;

const CounterCell = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 10px 8px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  text-align: center;
`;

// "SMS sent" is not a call status, so it sits apart from the call counters
// and carries the SMS accent colour instead of the neutral one.
const SmsCounterCell = styled(CounterCell)`
  border-color: #2563eb55;
  background: #2563eb12;

  & > div:first-child {
    color: #2563eb;
  }
`;

const SubLabel = styled.div`
  margin: 14px 0 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: ${({ theme }) => theme.colors.secondary};
`;

const CounterValue = styled.div`
  font-size: 18px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
`;

const CounterLabel = styled.div`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.secondary};
`;

// SCampaignCreate/Update. calling_hours/retry (calling window, priority
// hours, weekdays, retry policy) are edited right here, via
// campaignScheduleFields() — a new campaign gets the backend's own defaults
// for both sections (the "sparse section" convention, same as the agent's
// engine sections) until an operator changes them.
//
// starts_at/ends_at are date-only in the UI (VOAD-56: "День начала"/"День
// конца") even though the backend column is a full datetime — ends_at is
// sent with `endOfDay: true` (see ResourceForm's buildPayload) so picking a
// day means "runs through the end of that day", not "stops at its midnight".
const campaignFields = (agents) => [
  { name: 'name', labelKey: 'campaigns.fields.name', type: 'text', required: true },
  {
    name: 'description',
    labelKey: 'campaigns.fields.description',
    type: 'textarea',
    rows: 2,
    nullable: true,
    emptyValue: '',
  },
  {
    name: 'agent_id',
    labelKey: 'campaigns.fields.agent',
    type: 'select',
    asNumber: true,
    required: true,
    options: (agents || []).map((a) => ({ value: a.id, label: `${a.name} (#${a.id})` })),
  },
  {
    name: 'call_script',
    labelKey: 'campaigns.fields.callScript',
    type: 'textarea',
    rows: 6,
    hintKey: 'campaigns.fields.callScriptHint',
    emptyValue: '',
  },
  {
    name: 'starts_at',
    labelKey: 'campaigns.fields.startsAt',
    type: 'date',
    nullable: true,
    hintKey: 'campaigns.fields.dateHint',
  },
  {
    name: 'ends_at',
    labelKey: 'campaigns.fields.endsAt',
    type: 'date',
    nullable: true,
    hintKey: 'campaigns.fields.dateHint',
    endOfDay: true,
  },
  ...campaignScheduleFields(),
];

export const CampaignsPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const user = useUser();
  const canManage = canWrite('campaigns', user?.role);

  const [agents, setAgents] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [searchInput, setSearchInput] = useState('');
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState(null);
  // Guards against an older request's response landing after a newer one's
  // (e.g. clicking two status chips in quick succession) and silently
  // overwriting the correct, more-recent result with a stale one.
  const fetchSeq = useRef(0);

  const [detail, setDetail] = useState(null); // { id, data?, error?, counters? }
  const [modal, setModal] = useState(null); // { mode: 'create'|'edit', row? }
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [createAudienceId, setCreateAudienceId] = useState('');
  const [saving, setSaving] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);

  const [upload, setUpload] = useState(null); // { id, text, busy, result?, error? }
  const [audiences, setAudiences] = useState([]);
  const [addAudience, setAddAudience] = useState(null); // { id, audienceId, busy, result?, error? }
  const [deleting, setDeleting] = useState(null); // row pending delete confirm
  const [removing, setRemoving] = useState(false);
  const [restartConfirm, setRestartConfirm] = useState(false);
  const [archiving, setArchiving] = useState(false);

  useEffect(() => {
    agentsApi
      .list({ limit: MAX_PAGE })
      .then((data) => setAgents(Array.isArray(data) ? data : []))
      .catch(() => undefined);
    audiencesApi
      .list({ limit: MAX_PAGE })
      .then((res) => setAudiences(Array.isArray(res?.data) ? res.data : []))
      .catch(() => undefined);
  }, []);

  const agentById = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);
  const agentLabel = useCallback(
    (id) => {
      if (id === null || id === undefined) return '—';
      const a = agentById.get(id);
      return a ? a.name : `#${id}`;
    },
    [agentById]
  );

  // The search box is debounced into `filters.search` so typing doesn't fire
  // a request per keystroke; every other filter re-fetches immediately.
  useEffect(() => {
    const handle = setTimeout(() => {
      const trimmed = searchInput.trim();
      setFilters((prev) => (prev.search === trimmed ? prev : { ...prev, search: trimmed }));
    }, 400);
    return () => clearTimeout(handle);
  }, [searchInput]);

  const fetchCampaigns = useCallback(
    ({ keepRows = false, background = false } = {}) => {
      if (!keepRows && !background) setRows(null);
      if (!background) {
        setRefreshing(true);
        setLoadError(null);
      }
      const seq = ++fetchSeq.current;
      const { status, created_to, ...rest } = filters;
      return campaignsApi
        .list({
          ...rest,
          status: status.length ? status : undefined,
          // Inclusive upper bound (backend: created_to) on a date-only input —
          // stretch it to the end of that calendar day.
          created_to: created_to ? `${created_to}T23:59:59` : undefined,
          limit: pageSize,
          offset,
        })
        .then((res) => {
          if (seq !== fetchSeq.current) return; // a newer request already resolved
          setRows(Array.isArray(res?.data) ? res.data : []);
          setTotal(res?.count ?? 0);
          if (background) setLoadError(null);
        })
        .catch((e) => {
          if (seq !== fetchSeq.current || background) return;
          setLoadError(e.message);
          setRows([]);
          setTotal(0);
        })
        .finally(() => {
          if (!background && seq === fetchSeq.current) setRefreshing(false);
        });
    },
    [filters, offset, pageSize]
  );

  useEffect(() => {
    fetchCampaigns();
  }, [fetchCampaigns]);

  const reload = () => fetchCampaigns({ keepRows: true });

  const setFilter = (key, value) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, [key]: value }));
  };
  const toggleStatus = (status) => {
    setOffset(0);
    setFilters((prev) => ({
      ...prev,
      status: prev.status.includes(status)
        ? prev.status.filter((s) => s !== status)
        : [...prev.status, status],
    }));
  };
  const resetFilters = () => {
    setOffset(0);
    setFilters(EMPTY_FILTERS);
    setSearchInput('');
  };
  const changePageSize = (size) => {
    setOffset(0);
    setPageSize(size);
  };
  const filtersDirty = Boolean(
    filters.status.length ||
      filters.agent_id ||
      filters.search ||
      filters.created_from ||
      filters.created_to ||
      filters.include_archived ||
      filters.sort
  );

  const loadCounters = async (campaignId) => {
    const res = await campaignsApi.counters(campaignId);
    const counters = { total: res?.total ?? 0, sms_sent: res?.sms_sent ?? 0 };
    (res?.by_status || []).forEach(({ status, count }) => {
      counters[status] = count;
    });
    return counters;
  };

  const loadReasons = async (campaignId) => {
    const res = await campaignsApi.reasonBreakdown(campaignId);
    return Array.isArray(res?.categories) ? res.categories : [];
  };

  const openDetail = async (row) => {
    setDetail({ id: row.id, data: row });
    try {
      const [data, counters, reasons] = await Promise.all([
        campaignsApi.get(row.id),
        loadCounters(row.id).catch(() => null),
        loadReasons(row.id).catch(() => null),
      ]);
      setDetail({ id: row.id, data, counters, reasons });
    } catch (e) {
      setDetail({ id: row.id, error: e.message });
    }
  };

  const closeDetail = () => setDetail(null);

  // Live updates (10 s, silent): the campaigns table while no modal is open,
  // and the open campaign's data + counters + reasons while only its own modal
  // is open (a stacked form/upload/delete modal pauses it too).
  const anyOtherModal = Boolean(modal || upload || addAudience || deleting || restartConfirm);
  useAutoRefresh(() => fetchCampaigns({ background: true }), {
    paused: Boolean(detail) || anyOtherModal,
  });
  const detailId = detail?.id;
  useAutoRefresh(
    async () => {
      const [data, counters, reasons] = await Promise.all([
        campaignsApi.get(detailId),
        loadCounters(detailId).catch(() => null),
        loadReasons(detailId).catch(() => null),
      ]);
      setDetail((prev) =>
        prev && prev.id === detailId
          ? {
              id: detailId,
              data,
              counters: counters ?? prev.counters,
              reasons: reasons ?? prev.reasons,
            }
          : prev
      );
    },
    { enabled: Boolean(detail?.data), paused: anyOtherModal }
  );

  const openCreate = () => {
    setFormValues(buildInitialValues(campaignFields(agents), null));
    setFormErrors({});
    setCreateAudienceId('');
    setModal({ mode: 'create' });
  };

  const openEdit = (row) => {
    setFormValues(buildInitialValues(campaignFields(agents), row));
    setFormErrors({});
    setModal({ mode: 'edit', row });
  };

  const submitForm = async () => {
    const fields = campaignFields(agents);
    const { payload, errors } = buildPayload(fields, formValues);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSaving(true);
    try {
      if (modal.mode === 'create') {
        const created = await campaignsApi.create(payload);
        toast(t('common.created'), 'success');
        if (createAudienceId) {
          try {
            const result = await campaignsApi.addAudience(created.id, createAudienceId);
            toast(
              t('campaigns.addAudience.result', {
                accepted: result.accepted,
                rejected: result.rejected,
              }),
              'success'
            );
          } catch (e) {
            toast(e.message, 'error');
          }
        }
      } else {
        await campaignsApi.update(modal.row.id, payload);
        toast(t('common.saved'), 'success');
        if (detail?.id === modal.row.id) openDetail({ id: modal.row.id });
      }
      setModal(null);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    setRemoving(true);
    try {
      await campaignsApi.remove(deleting.id);
      toast(t('common.deleted'), 'success');
      if (detail?.id === deleting.id) closeDetail();
      setDeleting(null);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setRemoving(false);
    }
  };

  const toggleArchiveCampaign = async () => {
    if (!detail?.data) return;
    setArchiving(true);
    try {
      const data = await campaignsApi.update(detail.data.id, { is_archived: !detail.data.is_archived });
      setDetail((prev) => ({ ...prev, data }));
      toast(t('common.saved'), 'success');
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setArchiving(false);
    }
  };

  const runLifecycle = async (action) => {
    if (!detail?.id) return;
    setLifecycleBusy(true);
    try {
      const data = await campaignsApi[action](detail.id);
      setDetail((prev) => ({ ...prev, data }));
      const toastKey =
        action === 'start'
          ? 'started'
          : action === 'pause'
            ? 'paused'
            : action === 'complete'
              ? 'completed'
              : action === 'restart'
                ? 'restarted'
                : 'errored';
      toast(t(`campaigns.lifecycle.${toastKey}`), 'success');
      // The reset changes per-status call counters; refresh the open modal.
      if (action === 'restart') {
        loadCounters(detail.id)
          .then((counters) =>
            setDetail((prev) => (prev?.id === detail.id ? { ...prev, counters } : prev))
          )
          .catch(() => {});
      }
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setLifecycleBusy(false);
    }
  };

  const openUpload = () => {
    if (!detail?.id) return;
    setUpload({ id: detail.id, text: '', busy: false });
  };

  const openAddAudience = () => {
    if (!detail?.id) return;
    setAddAudience({ id: detail.id, audienceId: audiences[0]?.id ?? '', busy: false });
  };

  const submitAddAudience = async () => {
    if (!addAudience.audienceId) return;
    setAddAudience((prev) => ({ ...prev, busy: true, error: null }));
    try {
      const result = await campaignsApi.addAudience(addAudience.id, addAudience.audienceId);
      setAddAudience((prev) => ({ ...prev, busy: false, result }));
      reload();
      if (detail?.id === addAudience.id) openDetail({ id: addAudience.id });
    } catch (e) {
      setAddAudience((prev) => ({ ...prev, busy: false, error: e.message }));
    }
  };

  const submitUpload = async () => {
    let contacts;
    try {
      contacts = parseContactsInput(upload.text);
    } catch (_) {
      setUpload((prev) => ({ ...prev, error: t('campaigns.upload.invalid') }));
      return;
    }
    if (contacts.length === 0) {
      setUpload((prev) => ({ ...prev, error: t('campaigns.upload.invalid') }));
      return;
    }
    setUpload((prev) => ({ ...prev, busy: true, error: null }));
    try {
      const result = await campaignsApi.uploadContacts(upload.id, contacts);
      setUpload((prev) => ({ ...prev, busy: false, result }));
      reload();
      if (detail?.id === upload.id) openDetail({ id: upload.id });
    } catch (e) {
      setUpload((prev) => ({ ...prev, busy: false, error: e.message }));
    }
  };

  const nextActions = detail?.data ? NEXT_ACTIONS[detail.data.status] || [] : [];

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('campaigns.title')}</PageTitle>
        <HeaderActions>
          {canManage && (
            <PrimaryButton theme={theme} type="button" onClick={openCreate}>
              + {t('campaigns.create')}
            </PrimaryButton>
          )}
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        <FiltersBar>
          <Filter as="div" theme={theme}>
            {t('campaigns.filters.status')}
            <StatusChips>
              {statusValues(KINDS.CAMPAIGN).map((s) => (
                <StatusChip
                  key={s}
                  type="button"
                  theme={theme}
                  $active={filters.status.includes(s)}
                  onClick={() => toggleStatus(s)}
                >
                  {statusLabel(t, s, KINDS.CAMPAIGN)}
                </StatusChip>
              ))}
            </StatusChips>
          </Filter>

          <Filter theme={theme}>
            {t('campaigns.filters.agent')}
            <Select
              theme={theme}
              value={filters.agent_id}
              onChange={(e) => setFilter('agent_id', e.target.value)}
            >
              <option value="">{t('campaigns.filters.all')}</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} (#{a.id})
                </option>
              ))}
            </Select>
          </Filter>

          <Filter theme={theme}>
            {t('campaigns.filters.search')}
            <TextInput
              theme={theme}
              type="text"
              value={searchInput}
              placeholder={t('campaigns.filters.searchPlaceholder')}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('campaigns.filters.createdFrom')}
            <TextInput
              theme={theme}
              type="date"
              value={filters.created_from}
              onChange={(e) => setFilter('created_from', e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('campaigns.filters.createdTo')}
            <TextInput
              theme={theme}
              type="date"
              value={filters.created_to}
              onChange={(e) => setFilter('created_to', e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('campaigns.filters.sort')}
            <Select theme={theme} value={filters.sort} onChange={(e) => setFilter('sort', e.target.value)}>
              {SORT_OPTIONS.map(({ value, labelKey }) => (
                <option key={value || 'default'} value={value}>
                  {t(labelKey)}
                </option>
              ))}
            </Select>
          </Filter>

          <CheckboxLabel theme={theme} style={{ alignSelf: 'center' }}>
            <input
              type="checkbox"
              checked={filters.include_archived}
              onChange={(e) => setFilter('include_archived', e.target.checked)}
            />
            {t('common.showArchived')}
          </CheckboxLabel>

          <RefreshButton
            theme={theme}
            type="button"
            $busy={refreshing}
            disabled={refreshing}
            onClick={reload}
            title={t('campaigns.filters.refresh')}
            aria-label={t('campaigns.filters.refresh')}
          >
            <HiArrowPath />
          </RefreshButton>

          {filtersDirty && (
            <SecondaryButton theme={theme} type="button" onClick={resetFilters}>
              {t('campaigns.filters.reset')}
            </SecondaryButton>
          )}

          <CounterLabel theme={theme} style={{ marginLeft: 'auto', alignSelf: 'center' }}>
            {total}
          </CounterLabel>
        </FiltersBar>

        {rows === null ? (
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
        ) : loadError ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{loadError}</EmptyStateText>
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.noData')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{t('campaigns.empty')}</EmptyStateText>
          </EmptyState>
        ) : (
          <TableContainer theme={theme}>
            <Table>
              <TableHeader theme={theme}>
                <tr>
                  <TableHeaderCell theme={theme}>{t('common.id')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('campaigns.columns.name')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('common.status')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('campaigns.columns.agent')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('campaigns.columns.starts')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('campaigns.columns.ends')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('campaigns.columns.created')}</TableHeaderCell>
                </tr>
              </TableHeader>
              <tbody>
                {rows.map((row) => (
                  <TableRow
                    key={row.id}
                    theme={theme}
                    onClick={() => openDetail(row)}
                    style={{
                      cursor: 'pointer',
                      backgroundColor: row.status === 'error' ? 'rgba(239, 68, 68, 0.08)' : undefined,
                      borderLeft: row.status === 'error' ? '3px solid #ef4444' : undefined,
                    }}
                  >
                    <TableCell theme={theme}>{row.id}</TableCell>
                    <TableCell theme={theme}>
                      {row.name}
                      {row.is_archived && (
                        <Badge $color="#6b7280" style={{ marginLeft: 6 }}>
                          {t('common.archived')}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell theme={theme}>
                      <CampaignStatusBadge value={row.status} />
                    </TableCell>
                    <TableCell theme={theme}>{agentLabel(row.agent_id)}</TableCell>
                    <TableCell theme={theme}>{formatDateTime(row.starts_at)}</TableCell>
                    <TableCell theme={theme}>{formatDateTime(row.ends_at)}</TableCell>
                    <TableCell theme={theme}>{formatDateTime(row.created_at)}</TableCell>
                  </TableRow>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
        <Pagination
          offset={offset}
          limit={pageSize}
          total={total}
          onChange={setOffset}
          pageSize={pageSize}
          onPageSizeChange={changePageSize}
        />
      </ContentScroll>

      {detail && (
        <Modal
          title={t('campaigns.detail.title', { id: detail.id })}
          onClose={closeDetail}
          wide
          footer={
            detail.data && canManage && (
              <>
                <DangerButton
                  theme={theme}
                  type="button"
                  disabled={Boolean(detail.counters) && detail.counters.total > 0}
                  title={
                    detail.counters && detail.counters.total > 0
                      ? t('campaigns.detail.deleteBlocked')
                      : undefined
                  }
                  onClick={() => setDeleting(detail.data)}
                >
                  {t('common.remove')}
                </DangerButton>
                <SecondaryButton theme={theme} type="button" onClick={() => openEdit(detail.data)}>
                  {t('campaigns.detail.edit')}
                </SecondaryButton>
                <SecondaryButton
                  theme={theme}
                  type="button"
                  disabled={archiving || (!detail.data.is_archived && detail.data.status === 'running')}
                  title={
                    !detail.data.is_archived && detail.data.status === 'running'
                      ? t('campaigns.detail.archiveBlocked')
                      : undefined
                  }
                  onClick={toggleArchiveCampaign}
                >
                  {archiving
                    ? t(detail.data.is_archived ? 'common.unarchiving' : 'common.archiving')
                    : t(detail.data.is_archived ? 'common.unarchive' : 'common.archive')}
                </SecondaryButton>
                <SecondaryButton theme={theme} type="button" onClick={openUpload}>
                  {t('campaigns.detail.uploadContacts')}
                </SecondaryButton>
                <SecondaryButton theme={theme} type="button" onClick={openAddAudience}>
                  {t('campaigns.detail.addAudience')}
                </SecondaryButton>
                {nextActions.map((action) =>
                  action === 'markError' ? (
                    <DangerButton
                      key={action}
                      theme={theme}
                      type="button"
                      disabled={lifecycleBusy}
                      onClick={() => runLifecycle(action)}
                    >
                      {t('campaigns.lifecycle.markError')}
                    </DangerButton>
                  ) : (
                    <PrimaryButton
                      key={action}
                      theme={theme}
                      type="button"
                      disabled={lifecycleBusy}
                      onClick={() => (action === 'restart' ? setRestartConfirm(true) : runLifecycle(action))}
                    >
                      {t(`campaigns.lifecycle.${action}`)}
                    </PrimaryButton>
                  )
                )}
              </>
            )
          }
        >
          {detail.error ? (
            <EmptyStateText theme={theme}>{detail.error}</EmptyStateText>
          ) : !detail.data ? (
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
          ) : (
            <CampaignDetail
              data={detail.data}
              counters={detail.counters}
              reasons={detail.reasons}
              theme={theme}
              t={t}
              agentLabel={agentLabel}
            />
          )}
        </Modal>
      )}

      {modal && (
        <Modal
          title={
            modal.mode === 'create'
              ? `${t('common.create')} — ${t('campaigns.title')}`
              : `${t('common.edit')} #${modal.row.id} — ${t('campaigns.title')}`
          }
          onClose={() => setModal(null)}
          wide
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setModal(null)}>
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton theme={theme} type="button" disabled={saving} onClick={submitForm}>
                {saving ? t('common.saving') : t('common.save')}
              </PrimaryButton>
            </>
          }
        >
          <ResourceForm
            fields={campaignFields(agents)}
            values={formValues}
            errors={formErrors}
            onChange={setFormValues}
          />
          {modal.mode === 'create' && (
            <Filter theme={theme}>
              {t('campaigns.fields.audience')}
              <Select
                theme={theme}
                value={createAudienceId}
                onChange={(e) => setCreateAudienceId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">{t('campaigns.fields.audienceNone')}</option>
                {audiences.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} (#{a.id}, {a.member_count ?? 0})
                  </option>
                ))}
              </Select>
            </Filter>
          )}
        </Modal>
      )}

      {upload && (
        <Modal
          title={t('campaigns.upload.title', { id: upload.id })}
          onClose={() => setUpload(null)}
          wide
          footer={
            !upload.result && (
              <>
                <SecondaryButton theme={theme} type="button" onClick={() => setUpload(null)}>
                  {t('common.cancel')}
                </SecondaryButton>
                <PrimaryButton theme={theme} type="button" disabled={upload.busy} onClick={submitUpload}>
                  {upload.busy ? t('campaigns.upload.uploading') : t('campaigns.upload.submit')}
                </PrimaryButton>
              </>
            )
          }
        >
          {upload.result ? (
            <>
              <EmptyStateText theme={theme}>
                {t('campaigns.upload.result', {
                  accepted: upload.result.accepted,
                  rejected: upload.result.rejected,
                })}
              </EmptyStateText>
              <ResultTable theme={theme}>
                <thead>
                  <tr>
                    <th>{t('campaigns.upload.resultPhone')}</th>
                    <th>{t('campaigns.upload.resultCallId')}</th>
                    <th>{t('campaigns.upload.resultError')}</th>
                  </tr>
                </thead>
                <tbody>
                  {upload.result.results.map((r, i) => (
                    <tr key={i}>
                      <td>{r.phone}</td>
                      <td>{r.call_id ?? '—'}</td>
                      <td style={{ color: r.error ? '#dc2626' : undefined }}>{r.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </ResultTable>
            </>
          ) : (
            <>
              <EmptyStateText theme={theme}>{t('campaigns.upload.hint')}</EmptyStateText>
              <UploadArea
                theme={theme}
                value={upload.text}
                placeholder={t('campaigns.upload.placeholder')}
                onChange={(e) => setUpload((prev) => ({ ...prev, text: e.target.value }))}
                spellCheck={false}
              />
              {upload.error && <EmptyStateText theme={theme}>{upload.error}</EmptyStateText>}
            </>
          )}
        </Modal>
      )}

      {addAudience && (
        <Modal
          title={t('campaigns.addAudience.title', { id: addAudience.id })}
          onClose={() => setAddAudience(null)}
          footer={
            !addAudience.result && (
              <>
                <SecondaryButton theme={theme} type="button" onClick={() => setAddAudience(null)}>
                  {t('common.cancel')}
                </SecondaryButton>
                <PrimaryButton
                  theme={theme}
                  type="button"
                  disabled={addAudience.busy || !addAudience.audienceId}
                  onClick={submitAddAudience}
                >
                  {addAudience.busy ? t('campaigns.addAudience.adding') : t('campaigns.addAudience.submit')}
                </PrimaryButton>
              </>
            )
          }
        >
          {addAudience.result ? (
            <>
              <EmptyStateText theme={theme}>
                {t('campaigns.addAudience.result', {
                  accepted: addAudience.result.accepted,
                  rejected: addAudience.result.rejected,
                })}
              </EmptyStateText>
              <ResultTable theme={theme}>
                <thead>
                  <tr>
                    <th>{t('campaigns.addAudience.resultPhone')}</th>
                    <th>{t('campaigns.addAudience.resultError')}</th>
                  </tr>
                </thead>
                <tbody>
                  {addAudience.result.results.map((r, i) => (
                    <tr key={i}>
                      <td>{r.phone}</td>
                      <td style={{ color: r.error ? '#dc2626' : undefined }}>{r.error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </ResultTable>
            </>
          ) : audiences.length === 0 ? (
            <EmptyStateText theme={theme}>{t('campaigns.addAudience.noAudiences')}</EmptyStateText>
          ) : (
            <>
              <Filter theme={theme}>
                {t('campaigns.addAudience.select')}
                <Select
                  theme={theme}
                  value={addAudience.audienceId}
                  onChange={(e) =>
                    setAddAudience((prev) => ({ ...prev, audienceId: Number(e.target.value) }))
                  }
                >
                  {audiences.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} (#{a.id})
                    </option>
                  ))}
                </Select>
              </Filter>
              {addAudience.error && <EmptyStateText theme={theme}>{addAudience.error}</EmptyStateText>}
            </>
          )}
        </Modal>
      )}

      {restartConfirm && (
        <Modal
          title={`${t('campaigns.lifecycle.restart')} #${detail?.id}?`}
          onClose={() => !lifecycleBusy && setRestartConfirm(false)}
          footer={
            <>
              <SecondaryButton
                theme={theme}
                type="button"
                disabled={lifecycleBusy}
                onClick={() => setRestartConfirm(false)}
              >
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton
                theme={theme}
                type="button"
                disabled={lifecycleBusy}
                onClick={async () => {
                  await runLifecycle('restart');
                  setRestartConfirm(false);
                }}
              >
                {lifecycleBusy ? t('campaigns.lifecycle.restarting') : t('campaigns.lifecycle.restart')}
              </PrimaryButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>
            {t('campaigns.lifecycle.restartConfirm', {
              n: (detail?.counters?.exhausted ?? 0) + (detail?.counters?.canceled ?? 0),
            })}
          </EmptyStateText>
        </Modal>
      )}

      {deleting && (
        <Modal
          title={`${t('common.remove')} #${deleting.id}?`}
          onClose={() => !removing && setDeleting(null)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" disabled={removing} onClick={() => setDeleting(null)}>
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton theme={theme} type="button" disabled={removing} onClick={confirmDelete}>
                {removing ? t('common.removing') : t('common.remove')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>{t('common.irreversible')}</EmptyStateText>
        </Modal>
      )}
    </PageContent>
  );
};

const CampaignDetail = ({ data, counters, reasons, theme, t, agentLabel }) => {
  const Field = ({ label, children }) => (
    <>
      <DetailKey theme={theme}>{label}</DetailKey>
      <DetailValue theme={theme}>{children}</DetailValue>
    </>
  );

  return (
    <>
      <DetailGrid>
        <Field label={t('campaigns.detail.status')}>
          <CampaignStatusBadge value={data.status} />
        </Field>
        <Field label={t('campaigns.detail.agent')}>{agentLabel(data.agent_id)}</Field>
        <Field label={t('campaigns.detail.starts')}>{formatDateTime(data.starts_at)}</Field>
        <Field label={t('campaigns.detail.ends')}>{formatDateTime(data.ends_at)}</Field>
        <Field label={t('campaigns.detail.created')}>{formatDateTime(data.created_at)}</Field>
      </DetailGrid>

      <Section>
        <SectionLabel theme={theme}>
          {t('campaigns.detail.counters')} <span>{t('campaigns.detail.countersHint')}</span>
        </SectionLabel>
        {!counters ? (
          <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
        ) : (
          <CounterRow>
            <CounterCell theme={theme}>
              <CounterValue theme={theme}>{counters.total}</CounterValue>
              <CounterLabel theme={theme}>{t('campaigns.detail.counterTotal')}</CounterLabel>
            </CounterCell>
            {statusValues(KINDS.CALL).map((status) => (
              <CounterCell key={status} theme={theme}>
                <CounterValue theme={theme}>{counters[status] ?? 0}</CounterValue>
                <CounterLabel theme={theme}>
                  {statusLabel(t, status, KINDS.CALL)}
                </CounterLabel>
              </CounterCell>
            ))}
          </CounterRow>
        )}
        {counters && (
          <>
            <SubLabel theme={theme}>{t('campaigns.detail.smsSection')}</SubLabel>
            <CounterRow>
              <SmsCounterCell theme={theme}>
                <CounterValue theme={theme}>{counters.sms_sent ?? 0}</CounterValue>
                <CounterLabel theme={theme}>{t('campaigns.detail.counterSmsSent')}</CounterLabel>
              </SmsCounterCell>
            </CounterRow>
          </>
        )}
      </Section>

      {reasons && reasons.length > 0 && (
        <Section>
          <SectionLabel theme={theme}>{t('campaigns.detail.reasons')}</SectionLabel>
          <CounterRow>
            {reasons.map(({ reason_category: category, count }) => (
              <CounterCell key={category} theme={theme}>
                <CounterValue theme={theme}>{count}</CounterValue>
                <CounterLabel theme={theme}>
                  {t(`calls.reasonCategories.${category}`) || String(category).replace(/_/g, ' ')}
                </CounterLabel>
              </CounterCell>
            ))}
          </CounterRow>
        </Section>
      )}

      {data.call_script && (
        <Section>
          <SectionLabel theme={theme}>{t('campaigns.detail.callScript')}</SectionLabel>
          <DetailValue theme={theme}>{data.call_script}</DetailValue>
        </Section>
      )}

      <Section>
        <SectionLabel theme={theme}>{t('campaigns.detail.callingHours')}</SectionLabel>
        <DetailValue theme={theme}>
          {t('campaigns.detail.callingHoursLine', {
            tz: data.calling_hours.timezone,
            window:
              data.calling_hours.start || data.calling_hours.end
                ? `${data.calling_hours.start ?? '00:00'}–${data.calling_hours.end ?? '24:00'}`
                : t('campaigns.detail.anyTime'),
            days:
              data.calling_hours.weekdays.length >= 7
                ? t('campaigns.detail.everyDay')
                : [...data.calling_hours.weekdays]
                    .sort((a, b) => a - b)
                    .map((day) => t('campaigns.detail.weekdayShort', { day }))
                    .join(', '),
          })}
        </DetailValue>
      </Section>

      <Section>
        <SectionLabel theme={theme}>{t('campaigns.detail.retry')}</SectionLabel>
        <DetailValue theme={theme}>
          {t('campaigns.detail.retryLine', {
            maxAttempts: data.retry.max_attempts,
            busy: t('campaigns.detail.duration', { seconds: data.retry.busy_delay_seconds }),
            noAnswer: t('campaigns.detail.duration', { seconds: data.retry.no_answer_delay_seconds }),
            failed: t('campaigns.detail.duration', { seconds: data.retry.failed_delay_seconds }),
          })}
        </DetailValue>
      </Section>
    </>
  );
};
