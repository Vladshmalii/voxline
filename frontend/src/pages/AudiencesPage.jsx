import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import styled, { keyframes } from 'styled-components';
import { HiArrowPath } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { Modal } from 'components/Modal';
import { Pagination } from 'components/Pagination';
import { useClientCallHistory, ClientCallHistoryModal } from 'components/ClientCallHistoryModal';
import { toast } from 'components/Toaster';
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
  ResultTable,
  RowActionButton,
  CheckboxLabel,
  formatDateTime,
} from 'components/ui';
import { KINDS, statusValues, statusColor } from 'utils/statusMap';
import { audiencesApi, clientsApi, campaignsApi, MAX_PAGE } from 'utils/callApi';
import { fetchWithRefresh } from 'utils/api';
import { apiBase } from 'utils/apiBase';
import { useUser } from 'contexts/UserContext';
import { canWrite } from 'utils/permissions';

// VOAD-32: client status-segment import (`POST /clients/import/csv`) is a
// separate, page-level flow — not scoped to one audience, so it is not part
// of `audiencesApi`. Not yet promoted into utils/callApi.js (a later node
// consolidating audience/client API calls owns that move); inlined here the
// same way `audiencesApi.uploadContactsCsv` builds its request, minus the
// per-audience id.
const CLIENT_IMPORT_CSV_PATH = '/api/v1/clients/import/csv';

/** Extracts a human-readable message from a FastAPI error response. */
const formatClientImportError = (data, status) => {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : '';
        return loc ? `${loc}: ${e.msg}` : e.msg;
      })
      .join('; ');
  }
  return `Request failed (${status})`;
};

/**
 * Imports a status-segment CSV of clients. Response: SClientImportRead.
 * `audienceName`, if given, also files every accepted row under that named
 * Audience (created if it doesn't exist yet) — so it shows up in "История
 * загрузок" and becomes filterable from the lead table.
 */
const importClientsCsv = async (file, audienceName) => {
  const base = apiBase();
  const form = new FormData();
  form.append('file', file);
  if (audienceName && audienceName.trim()) form.append('audience_name', audienceName.trim());
  const res = await fetchWithRefresh(`${base}${CLIENT_IMPORT_CSV_PATH}`, {
    method: 'POST',
    body: form,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(formatClientImportError(data, res.status));
  }
  return data;
};

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

const FileRow = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
`;

const FileName = styled.span`
  font-size: 13px;
  color: ${({ theme }) => theme.colors.secondary};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

// ── VOAD-34: lead table (GET /clients) ──────────────────────────────────────
// This page's whole `Client` base — status/segment/country/language/
// vip_status/last_active/last_deposit only live on Client, never on
// AudienceMember (see clients.py's module docstring).

// ClientStatusEnum values/colours/labels: utils/statusMap.js (client kind).
const CLIENT_STATUSES = statusValues(KINDS.CLIENT);

const DEFAULT_LEAD_PAGE_SIZE = 50;
const DEFAULT_MODAL_PAGE_SIZE = 10;
const MODAL_PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

const EMPTY_LEAD_FILTERS = {
  status: '',
  country: '',
  language: '',
  audience_id: '',
  last_active_from: '',
  last_active_to: '',
  search: '',
};

// A lead is highlighted as invalid/incomplete when it is missing a field an
// operator needs to actually call or address it: `phone` is non-nullable on
// Client so this is defensive, but `name` and `status` are worth flagging —
// an empty name came from a CSV row that had a phone and nothing else useful.
const isInvalidLead = (row) => !row?.phone || !row?.name || !row?.status;

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

  select,
  input {
    min-width: 140px;
  }
`;

// Invalid/incomplete rows get a soft red wash across the whole row, plus the
// "Incomplete" badge in the row itself — the wash alone would be invisible to
// anyone relying on a screen reader or a black-and-white printout.
const LeadRow = styled(TableRow)`
  background: ${({ $invalid, theme }) =>
    $invalid ? (theme.colors.primary === '#0D0D0D' ? '#fef2f2' : 'rgba(220,38,38,0.12)') : 'transparent'};
`;

const HistoryTable = styled(Table)`
  margin-bottom: 16px;
`;

const BackLink = styled.button`
  background: none;
  border: none;
  padding: 0;
  margin-bottom: 12px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.accentNeon || theme.colors.secondary};
  cursor: pointer;
  text-decoration: underline;
`;

export const AudiencesPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const user = useUser();
  const canManage = canWrite('audiences', user?.role);

  // Full per-audience CRUD (create/upload-to-audience) still isn't managed
  // from this screen (removed at the user's earlier request — it was
  // redundant with the Leads view below) — but delete/archive are (see
  // `audienceManage` further down). This background list is fetched with
  // `include_archived: true` unconditionally, since it also resolves an
  // upload batch's audience_id to a name in the History panel and an
  // archived audience should still resolve to its real name there, not
  // "#id"; `activeAudiences` below is the filtered view for pickers that
  // must not offer an archived one (the lead filter, the CSV-import
  // audience-name datalist).
  const [audiences, setAudiences] = useState([]);
  const audienceById = useMemo(() => new Map(audiences.map((a) => [a.id, a])), [audiences]);
  const activeAudiences = useMemo(() => audiences.filter((a) => !a.is_archived), [audiences]);

  const loadAudiences = useCallback(() => {
    audiencesApi
      .list({ limit: MAX_PAGE, include_archived: true })
      .then((res) => setAudiences(Array.isArray(res?.data) ? res.data : []))
      .catch(() => setAudiences([]));
  }, []);

  useEffect(() => {
    loadAudiences();
  }, [loadAudiences]);

  // Only fetched to resolve a call's campaign_id to a name in the per-lead
  // call history panel below — same "quiet background fetch" pattern as
  // `audiences` above.
  const [campaigns, setCampaigns] = useState([]);
  const campaignById = useMemo(() => new Map(campaigns.map((c) => [c.id, c])), [campaigns]);

  const [countries, setCountries] = useState([]);

  useEffect(() => {
    campaignsApi
      .list({ limit: MAX_PAGE })
      .then((res) => setCampaigns(Array.isArray(res?.data) ? res.data : []))
      .catch(() => setCampaigns([]));
    clientsApi
      .listCountries()
      .then((data) => setCountries(Array.isArray(data) ? data : []))
      .catch(() => setCountries([]));
  }, []);

  const [clientImport, setClientImport] = useState(null); // { file, busy, result?, error? }
  const [editingLead, setEditingLead] = useState(null);
  const [leadForm, setLeadForm] = useState({ name: '', phone: '', status: 'active', country: '', language: '', idle_timeout_seconds: '' });
  const [leadFormBusy, setLeadFormBusy] = useState(false);

  // VOAD-34 lead table (GET /clients).
  const [leadRows, setLeadRows] = useState(null);
  const [leadTotal, setLeadTotal] = useState(0);
  const [leadOffset, setLeadOffset] = useState(0);
  const [leadPageSize, setLeadPageSize] = useState(DEFAULT_LEAD_PAGE_SIZE);
  const [leadRefreshing, setLeadRefreshing] = useState(false);
  const [leadLoadError, setLeadLoadError] = useState(null);
  // Guards against an older request's response landing after a newer one's
  // (e.g. typing quickly, or toggling a filter right after another) and
  // silently overwriting the correct, more-recent result with a stale one.
  const leadFetchSeq = useRef(0);
  const [leadFilters, setLeadFilters] = useState(EMPTY_LEAD_FILTERS);
  // Seeded from ?search= when arriving via a call detail's "Open this lead"
  // link (CallsPage.jsx navigates here with the phone number, since a lead
  // has no dedicated route of its own to link to directly).
  const [searchParams] = useSearchParams();
  const [leadSearchInput, setLeadSearchInput] = useState(() => searchParams.get('search') || '');

  // Upload-batch history panel. `drill` holds the selected batch's own lead
  // sub-list, rendered in place of the history table rather than as a second
  // stacked modal.
  const [uploadHistory, setUploadHistory] = useState(null); // { rows, total, busy, error, drill? }

  // Per-lead call history — clicking any lead row (main table or a batch
  // drill-down) opens this: every Call for that client across every campaign.
  const {
    callHistory,
    open: openCallHistory,
    close: closeCallHistory,
    changeOffset: changeCallHistoryOffset,
    changePageSize: changeCallHistoryPageSize,
  } = useClientCallHistory();

  // Search is debounced into `leadFilters.search` so typing doesn't fire a
  // request per keystroke — same convention as CampaignsPage's search box.
  useEffect(() => {
    const handle = setTimeout(() => {
      const trimmed = leadSearchInput.trim();
      setLeadFilters((prev) => (prev.search === trimmed ? prev : { ...prev, search: trimmed }));
    }, 400);
    return () => clearTimeout(handle);
  }, [leadSearchInput]);

  const fetchLeads = useCallback(
    ({ keepRows = false } = {}) => {
      if (!keepRows) setLeadRows(null);
      setLeadRefreshing(true);
      setLeadLoadError(null);
      const seq = ++leadFetchSeq.current;
      const { last_active_from, last_active_to, ...rest } = leadFilters;
      clientsApi
        .list({
          ...rest,
          // Date-only inputs stretched to inclusive datetime bounds — same
          // convention as CampaignsPage's created_from/created_to.
          last_active_from: last_active_from ? `${last_active_from}T00:00:00` : undefined,
          last_active_to: last_active_to ? `${last_active_to}T23:59:59` : undefined,
          limit: leadPageSize,
          offset: leadOffset,
        })
        .then((res) => {
          if (seq !== leadFetchSeq.current) return; // a newer request already resolved
          setLeadRows(Array.isArray(res?.data) ? res.data : []);
          setLeadTotal(res?.count ?? 0);
        })
        .catch((e) => {
          if (seq !== leadFetchSeq.current) return;
          setLeadLoadError(e.message);
          setLeadRows([]);
          setLeadTotal(0);
        })
        .finally(() => {
          if (seq === leadFetchSeq.current) setLeadRefreshing(false);
        });
    },
    [leadFilters, leadOffset, leadPageSize]
  );

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  const reloadLeads = () => fetchLeads({ keepRows: true });

  const setLeadFilter = (key, value) => {
    setLeadOffset(0);
    setLeadFilters((prev) => ({ ...prev, [key]: value }));
  };

  const changeLeadPageSize = (size) => {
    setLeadOffset(0);
    setLeadPageSize(size);
  };

  const resetLeadFilters = () => {
    setLeadOffset(0);
    setLeadFilters(EMPTY_LEAD_FILTERS);
    setLeadSearchInput('');
  };

  const leadFiltersDirty = Boolean(
    leadFilters.status ||
      leadFilters.country ||
      leadFilters.language ||
      leadFilters.audience_id ||
      leadFilters.last_active_from ||
      leadFilters.last_active_to ||
      leadFilters.search
  );

  const loadUploadHistoryPage = (offset, pageSize) => {
    setUploadHistory((prev) => ({ ...prev, rows: null, busy: false, error: null, offset, pageSize, drill: null }));
    audiencesApi
      .listUploads({ limit: pageSize, offset })
      .then((res) => {
        setUploadHistory((prev) =>
          prev
            ? { ...prev, rows: Array.isArray(res?.data) ? res.data : [], total: res?.count ?? 0 }
            : prev
        );
      })
      .catch((e) => {
        setUploadHistory((prev) => (prev ? { ...prev, rows: [], error: e.message } : prev));
      });
  };

  const openUploadHistory = () => {
    setUploadHistory({
      rows: null,
      total: 0,
      busy: false,
      error: null,
      offset: 0,
      pageSize: DEFAULT_MODAL_PAGE_SIZE,
    });
    loadUploadHistoryPage(0, DEFAULT_MODAL_PAGE_SIZE);
  };

  const changeUploadHistoryOffset = (offset) => loadUploadHistoryPage(offset, uploadHistory.pageSize);
  const changeUploadHistoryPageSize = (pageSize) => loadUploadHistoryPage(0, pageSize);

  const closeUploadHistory = () => setUploadHistory(null);

  // Drill down to one batch's leads. Only meaningful when the batch targeted
  // an audience — a VOAD-32 status-segment import has `audience_id: null` and
  // there is no per-upload-event tag on Client/AudienceMember to filter by
  // instead (see GET /audiences/uploads's own docstring on the backend).
  const drillIntoBatch = (batch, offset = 0, pageSize = DEFAULT_MODAL_PAGE_SIZE) => {
    if (batch.audience_id == null) return;
    setUploadHistory((prev) => ({
      ...prev,
      drill: { batch, rows: null, error: null, offset, pageSize },
    }));
    clientsApi
      .list({ audience_id: batch.audience_id, limit: pageSize, offset })
      .then((res) => {
        setUploadHistory((prev) =>
          prev && prev.drill?.batch === batch
            ? {
                ...prev,
                drill: {
                  batch,
                  rows: Array.isArray(res?.data) ? res.data : [],
                  error: null,
                  offset,
                  pageSize,
                  total: res?.count ?? 0,
                },
              }
            : prev
        );
      })
      .catch((e) => {
        setUploadHistory((prev) =>
          prev && prev.drill?.batch === batch
            ? { ...prev, drill: { batch, rows: [], error: e.message, offset, pageSize } }
            : prev
        );
      });
  };

  const changeDrillOffset = (offset) =>
    drillIntoBatch(uploadHistory.drill.batch, offset, uploadHistory.drill.pageSize);
  const changeDrillPageSize = (pageSize) => drillIntoBatch(uploadHistory.drill.batch, 0, pageSize);

  const backToHistory = () => setUploadHistory((prev) => (prev ? { ...prev, drill: null } : prev));

  // Audience management: delete/archive. `busyId` disables both row actions
  // while a request for that row is in flight — one at a time is enough for
  // an admin tool, no need to track it per-action.
  const [audienceManage, setAudienceManage] = useState(null); // { rows, total, offset, pageSize, includeArchived, error }
  const [audienceDeleteConfirm, setAudienceDeleteConfirm] = useState(null); // audience row pending delete
  const [audienceBusyId, setAudienceBusyId] = useState(null);

  const loadAudienceManagePage = (offset, pageSize, includeArchived) => {
    setAudienceManage((prev) => ({ ...prev, rows: null, error: null, offset, pageSize, includeArchived }));
    audiencesApi
      .list({ limit: pageSize, offset, include_archived: includeArchived })
      .then((res) => {
        setAudienceManage((prev) =>
          prev ? { ...prev, rows: Array.isArray(res?.data) ? res.data : [], total: res?.count ?? 0 } : prev
        );
      })
      .catch((e) => {
        setAudienceManage((prev) => (prev ? { ...prev, rows: [], error: e.message } : prev));
      });
  };

  const openAudienceManage = () => {
    setAudienceManage({
      rows: null,
      total: 0,
      offset: 0,
      pageSize: DEFAULT_MODAL_PAGE_SIZE,
      includeArchived: false,
      error: null,
    });
    loadAudienceManagePage(0, DEFAULT_MODAL_PAGE_SIZE, false);
  };

  const closeAudienceManage = () => setAudienceManage(null);
  const changeAudienceManageOffset = (offset) =>
    loadAudienceManagePage(offset, audienceManage.pageSize, audienceManage.includeArchived);
  const changeAudienceManagePageSize = (pageSize) =>
    loadAudienceManagePage(0, pageSize, audienceManage.includeArchived);
  const changeAudienceManageIncludeArchived = (includeArchived) =>
    loadAudienceManagePage(0, audienceManage.pageSize, includeArchived);

  const toggleArchiveAudience = async (row) => {
    setAudienceBusyId(row.id);
    try {
      await audiencesApi.update(row.id, { is_archived: !row.is_archived });
      toast(t('common.saved'), 'success');
      loadAudienceManagePage(audienceManage.offset, audienceManage.pageSize, audienceManage.includeArchived);
      loadAudiences();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setAudienceBusyId(null);
    }
  };

  const confirmDeleteAudience = async () => {
    if (!audienceDeleteConfirm) return;
    setAudienceBusyId(audienceDeleteConfirm.id);
    try {
      await audiencesApi.remove(audienceDeleteConfirm.id);
      toast(t('common.deleted'), 'success');
      setAudienceDeleteConfirm(null);
      loadAudienceManagePage(audienceManage.offset, audienceManage.pageSize, audienceManage.includeArchived);
      loadAudiences();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setAudienceBusyId(null);
    }
  };

  const openClientImport = () => {
    setClientImport({ file: null, audienceName: '', busy: false });
  };

  const submitClientImport = async () => {
    if (!clientImport.file) {
      setClientImport((prev) => ({ ...prev, error: t('audiences.csvUpload.invalid') }));
      return;
    }
    setClientImport((prev) => ({ ...prev, busy: true, error: null }));
    try {
      const result = await importClientsCsv(clientImport.file, clientImport.audienceName);
      setClientImport((prev) => ({ ...prev, busy: false, result }));
      reloadLeads();
    } catch (e) {
      setClientImport((prev) => ({ ...prev, busy: false, error: e.message }));
    }
  };

  const openEditLead = (lead) => {
    setEditingLead(lead);
    setLeadForm({
      name: lead.name || '',
      phone: lead.phone || '',
      status: lead.status || 'active',
      country: lead.country || '',
      language: lead.language || '',
      idle_timeout_seconds: lead.idle_timeout_seconds ?? '',
    });
  };

  const handleSaveLead = async () => {
    if (!editingLead) return;
    setLeadFormBusy(true);
    try {
      await clientsApi.update(editingLead.id, {
        name: leadForm.name || null,
        phone: leadForm.phone,
        status: leadForm.status,
        country: leadForm.country || null,
        language: leadForm.language || null,
        idle_timeout_seconds:
          leadForm.idle_timeout_seconds === '' ? null : Number(leadForm.idle_timeout_seconds),
      });
      toast(t('audiences.leads.saved'), 'success');
      setEditingLead(null);
      reloadLeads();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setLeadFormBusy(false);
    }
  };

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('audiences.leads.title')}</PageTitle>
        <HeaderActions>
          <RefreshButton
            theme={theme}
            type="button"
            $busy={leadRefreshing}
            disabled={leadRefreshing}
            onClick={reloadLeads}
            title={t('campaigns.filters.refresh')}
            aria-label={t('campaigns.filters.refresh')}
          >
            <HiArrowPath />
          </RefreshButton>
          {canManage && (
            <SecondaryButton theme={theme} type="button" onClick={openClientImport}>
              {t('audiences.clientImport.button')}
            </SecondaryButton>
          )}
          <SecondaryButton theme={theme} type="button" onClick={openUploadHistory}>
            {t('audiences.uploadHistory.button')}
          </SecondaryButton>
          {canManage && (
            <SecondaryButton theme={theme} type="button" onClick={openAudienceManage}>
              {t('audiences.manage.button')}
            </SecondaryButton>
          )}
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        <FiltersBar>
          <Filter theme={theme}>
            {t('audiences.leads.search')}
            <TextInput
              theme={theme}
              type="text"
              value={leadSearchInput}
              placeholder={t('audiences.leads.searchPlaceholder')}
              onChange={(e) => setLeadSearchInput(e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('audiences.leads.status')}
            <Select theme={theme} value={leadFilters.status} onChange={(e) => setLeadFilter('status', e.target.value)}>
              <option value="">{t('audiences.leads.all')}</option>
              {CLIENT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`audiences.leads.statuses.${s}`)}
                </option>
              ))}
            </Select>
          </Filter>

          <Filter theme={theme}>
            {t('audiences.leads.audience')}
            <Select
              theme={theme}
              value={leadFilters.audience_id}
              onChange={(e) => setLeadFilter('audience_id', e.target.value)}
            >
              <option value="">{t('audiences.leads.all')}</option>
              {activeAudiences.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Filter>

          <Filter theme={theme}>
            {t('audiences.leads.country')}
            <Select
              theme={theme}
              value={leadFilters.country}
              onChange={(e) => setLeadFilter('country', e.target.value)}
            >
              <option value="">{t('audiences.leads.all')}</option>
              {countries.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </Filter>

          <Filter theme={theme} title={t('audiences.leads.exactMatch')}>
            {t('audiences.leads.language')}
            <TextInput
              theme={theme}
              type="text"
              value={leadFilters.language}
              onChange={(e) => setLeadFilter('language', e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('audiences.leads.lastActiveFrom')}
            <TextInput
              theme={theme}
              type="date"
              value={leadFilters.last_active_from}
              onChange={(e) => setLeadFilter('last_active_from', e.target.value)}
            />
          </Filter>

          <Filter theme={theme}>
            {t('audiences.leads.lastActiveTo')}
            <TextInput
              theme={theme}
              type="date"
              value={leadFilters.last_active_to}
              onChange={(e) => setLeadFilter('last_active_to', e.target.value)}
            />
          </Filter>

          {leadFiltersDirty && (
            <SecondaryButton theme={theme} type="button" onClick={resetLeadFilters}>
              {t('campaigns.filters.reset')}
            </SecondaryButton>
          )}
        </FiltersBar>

        {leadRows === null ? (
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
        ) : leadLoadError ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{leadLoadError}</EmptyStateText>
          </EmptyState>
        ) : leadRows.length === 0 ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.noData')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{t('audiences.leads.noMatch')}</EmptyStateText>
          </EmptyState>
        ) : (
          <>
            <LeadTable
              rows={leadRows}
              theme={theme}
              t={t}
              onRowClick={openCallHistory}
              onEdit={canManage ? openEditLead : undefined}
            />
            <Pagination
              offset={leadOffset}
              limit={leadPageSize}
              total={leadTotal}
              onChange={setLeadOffset}
              pageSize={leadPageSize}
              onPageSizeChange={changeLeadPageSize}
            />
          </>
        )}
      </ContentScroll>

      {clientImport && (
        <Modal
          title={t('audiences.clientImport.title')}
          onClose={() => setClientImport(null)}
          wide
          footer={
            !clientImport.result && (
              <>
                <SecondaryButton theme={theme} type="button" onClick={() => setClientImport(null)}>
                  {t('common.cancel')}
                </SecondaryButton>
                <PrimaryButton
                  theme={theme}
                  type="button"
                  disabled={clientImport.busy}
                  onClick={submitClientImport}
                >
                  {clientImport.busy ? t('audiences.csvUpload.uploading') : t('audiences.csvUpload.submit')}
                </PrimaryButton>
              </>
            )
          }
        >
          {clientImport.result ? (
            <ClientImportResult result={clientImport.result} theme={theme} t={t} />
          ) : (
            <>
              <EmptyStateText theme={theme}>{t('audiences.clientImport.hint')}</EmptyStateText>
              <FileRow>
                <SecondaryButton theme={theme} type="button" as="label" style={{ cursor: 'pointer' }}>
                  {t('audiences.csvUpload.chooseFile')}
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    hidden
                    onChange={(e) =>
                      setClientImport((prev) => ({ ...prev, file: e.target.files?.[0] ?? null, error: null }))
                    }
                  />
                </SecondaryButton>
                <FileName theme={theme}>
                  {clientImport.file ? clientImport.file.name : t('audiences.csvUpload.noFile')}
                </FileName>
              </FileRow>
              <Filter theme={theme}>
                {t('audiences.clientImport.audienceName')}
                <TextInput
                  theme={theme}
                  type="text"
                  list="audience-name-suggestions"
                  value={clientImport.audienceName}
                  placeholder={t('audiences.clientImport.audienceNamePlaceholder')}
                  onChange={(e) =>
                    setClientImport((prev) => ({ ...prev, audienceName: e.target.value }))
                  }
                />
                <datalist id="audience-name-suggestions">
                  {activeAudiences.map((a) => (
                    <option key={a.id} value={a.name} />
                  ))}
                </datalist>
              </Filter>
              <EmptyStateText theme={theme} style={{ marginBottom: 10 }}>
                {t('audiences.clientImport.audienceNameHint')}
              </EmptyStateText>
              {clientImport.error && <EmptyStateText theme={theme}>{clientImport.error}</EmptyStateText>}
            </>
          )}
        </Modal>
      )}

      {uploadHistory && (
        <Modal
          title={
            uploadHistory.drill
              ? t('audiences.uploadHistory.batchTitle', { id: uploadHistory.drill.batch.id })
              : t('audiences.uploadHistory.title')
          }
          onClose={closeUploadHistory}
          wide
          width="1080px"
        >
          {uploadHistory.drill ? (
            <>
              <BackLink theme={theme} type="button" onClick={backToHistory}>
                {t('audiences.uploadHistory.backToHistory')}
              </BackLink>
              <EmptyStateText theme={theme} style={{ marginBottom: 10 }}>
                {uploadHistory.drill.batch.filename || '—'} ·{' '}
                {t('audiences.uploadHistory.user', { id: uploadHistory.drill.batch.uploaded_by })} ·{' '}
                {formatDateTime(uploadHistory.drill.batch.created_at)} ·{' '}
                {uploadHistory.drill.batch.total_rows} {t('audiences.uploadHistory.columns.total').toLowerCase()},{' '}
                {uploadHistory.drill.batch.valid_rows} {t('audiences.uploadHistory.columns.valid').toLowerCase()},{' '}
                {uploadHistory.drill.batch.invalid_rows} {t('audiences.uploadHistory.columns.invalid').toLowerCase()}
              </EmptyStateText>
              {uploadHistory.drill.error ? (
                <EmptyStateText theme={theme}>{uploadHistory.drill.error}</EmptyStateText>
              ) : uploadHistory.drill.rows === null ? (
                <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
              ) : uploadHistory.drill.rows.length === 0 ? (
                <EmptyStateText theme={theme}>{t('audiences.uploadHistory.noLeadsForBatch')}</EmptyStateText>
              ) : (
                <>
                  <LeadTable rows={uploadHistory.drill.rows} theme={theme} t={t} onRowClick={openCallHistory} />
                  <Pagination
                    offset={uploadHistory.drill.offset}
                    limit={uploadHistory.drill.pageSize}
                    total={uploadHistory.drill.total}
                    onChange={changeDrillOffset}
                    pageSize={uploadHistory.drill.pageSize}
                    onPageSizeChange={changeDrillPageSize}
                    pageSizeOptions={MODAL_PAGE_SIZE_OPTIONS}
                  />
                </>
              )}
            </>
          ) : uploadHistory.error ? (
            <EmptyStateText theme={theme}>{uploadHistory.error}</EmptyStateText>
          ) : uploadHistory.rows === null ? (
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
          ) : uploadHistory.rows.length === 0 ? (
            <EmptyStateText theme={theme}>{t('audiences.uploadHistory.noUploads')}</EmptyStateText>
          ) : (
            <TableContainer theme={theme}>
              <HistoryTable>
                <TableHeader theme={theme}>
                  <tr>
                    <TableHeaderCell theme={theme}>{t('audiences.uploadHistory.columns.when')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('audiences.uploadHistory.columns.who')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('audiences.uploadHistory.columns.filename')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('audiences.uploadHistory.columns.audience')}</TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('audiences.uploadHistory.columns.total')}
                    </TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('audiences.uploadHistory.columns.valid')}
                    </TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('audiences.uploadHistory.columns.invalid')}
                    </TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('audiences.uploadHistory.columns.leads')}
                    </TableHeaderCell>
                  </tr>
                </TableHeader>
                <tbody>
                  {uploadHistory.rows.map((batch) => (
                    <TableRow key={batch.id} theme={theme}>
                      <TableCell theme={theme}>{formatDateTime(batch.created_at)}</TableCell>
                      <TableCell theme={theme}>{t('audiences.uploadHistory.user', { id: batch.uploaded_by })}</TableCell>
                      <TableCell theme={theme}>{batch.filename || '—'}</TableCell>
                      <TableCell theme={theme}>
                        {batch.audience_name ||
                          (batch.audience_id != null
                            ? audienceById.get(batch.audience_id)?.name || `#${batch.audience_id}`
                            : '—')}
                      </TableCell>
                      <TableCell theme={theme} $align="right">{batch.total_rows}</TableCell>
                      <TableCell theme={theme} $align="right">{batch.valid_rows}</TableCell>
                      <TableCell theme={theme} $align="right">
                        {batch.invalid_rows > 0 ? (
                          <Badge $color="#dc2626">{batch.invalid_rows}</Badge>
                        ) : (
                          batch.invalid_rows
                        )}
                      </TableCell>
                      <TableCell theme={theme} $align="right">
                        <RowActionButton
                          theme={theme}
                          type="button"
                          disabled={batch.audience_id == null}
                          title={batch.audience_id == null ? t('audiences.uploadHistory.notTiedToAudience') : undefined}
                          onClick={() => drillIntoBatch(batch)}
                        >
                          {t('audiences.uploadHistory.viewLeads')}
                        </RowActionButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </tbody>
              </HistoryTable>
            </TableContainer>
          )}
          {!uploadHistory.drill && !uploadHistory.error && uploadHistory.rows && uploadHistory.rows.length > 0 && (
            <Pagination
              offset={uploadHistory.offset}
              limit={uploadHistory.pageSize}
              total={uploadHistory.total}
              onChange={changeUploadHistoryOffset}
              pageSize={uploadHistory.pageSize}
              onPageSizeChange={changeUploadHistoryPageSize}
              pageSizeOptions={MODAL_PAGE_SIZE_OPTIONS}
            />
          )}
        </Modal>
      )}

      <ClientCallHistoryModal
        callHistory={callHistory}
        close={closeCallHistory}
        changeOffset={changeCallHistoryOffset}
        changePageSize={changeCallHistoryPageSize}
        campaignById={campaignById}
        theme={theme}
        t={t}
        onEdit={(lead) => {
          closeCallHistory();
          openEditLead(lead);
        }}
      />

      {audienceManage && (
        <Modal
          title={t('audiences.manage.title')}
          onClose={closeAudienceManage}
          wide
          width="900px"
        >
          <CheckboxLabel theme={theme} style={{ marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={audienceManage.includeArchived}
              onChange={(e) => changeAudienceManageIncludeArchived(e.target.checked)}
            />
            {t('common.showArchived')}
          </CheckboxLabel>
          {audienceManage.error ? (
            <EmptyStateText theme={theme}>{audienceManage.error}</EmptyStateText>
          ) : audienceManage.rows === null ? (
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
          ) : audienceManage.rows.length === 0 ? (
            <EmptyStateText theme={theme}>{t('audiences.manage.noAudiences')}</EmptyStateText>
          ) : (
            <>
              <TableContainer theme={theme}>
                <HistoryTable>
                  <TableHeader theme={theme}>
                    <tr>
                      <TableHeaderCell theme={theme}>{t('audiences.manage.columns.name')}</TableHeaderCell>
                      <TableHeaderCell theme={theme} $align="right">
                        {t('audiences.manage.columns.members')}
                      </TableHeaderCell>
                      <TableHeaderCell theme={theme}>{t('common.createdAt')}</TableHeaderCell>
                      <TableHeaderCell theme={theme}>{t('common.status')}</TableHeaderCell>
                      <TableHeaderCell theme={theme} $align="right">{t('common.actions')}</TableHeaderCell>
                    </tr>
                  </TableHeader>
                  <tbody>
                    {audienceManage.rows.map((a) => (
                      <TableRow key={a.id} theme={theme}>
                        <TableCell theme={theme}>{a.name}</TableCell>
                        <TableCell theme={theme} $align="right">{a.member_count}</TableCell>
                        <TableCell theme={theme}>{formatDateTime(a.created_at)}</TableCell>
                        <TableCell theme={theme}>
                          {a.is_archived ? <Badge $color="#6b7280">{t('common.archived')}</Badge> : '—'}
                        </TableCell>
                        <TableCell theme={theme} $align="right">
                          <RowActionButton
                            theme={theme}
                            type="button"
                            disabled={audienceBusyId === a.id}
                            onClick={() => toggleArchiveAudience(a)}
                            style={{ marginRight: 6 }}
                          >
                            {t(a.is_archived ? 'common.unarchive' : 'common.archive')}
                          </RowActionButton>
                          <RowActionButton
                            theme={theme}
                            type="button"
                            $danger
                            disabled={audienceBusyId === a.id}
                            onClick={() => setAudienceDeleteConfirm(a)}
                          >
                            {t('common.remove')}
                          </RowActionButton>
                        </TableCell>
                      </TableRow>
                    ))}
                  </tbody>
                </HistoryTable>
              </TableContainer>
              <Pagination
                offset={audienceManage.offset}
                limit={audienceManage.pageSize}
                total={audienceManage.total}
                onChange={changeAudienceManageOffset}
                pageSize={audienceManage.pageSize}
                onPageSizeChange={changeAudienceManagePageSize}
                pageSizeOptions={MODAL_PAGE_SIZE_OPTIONS}
              />
            </>
          )}
        </Modal>
      )}

      {audienceDeleteConfirm && (
        <Modal
          title={t('audiences.manage.deleteTitle', { name: audienceDeleteConfirm.name })}
          onClose={() => !audienceBusyId && setAudienceDeleteConfirm(null)}
          footer={
            <>
              <SecondaryButton
                theme={theme}
                type="button"
                disabled={Boolean(audienceBusyId)}
                onClick={() => setAudienceDeleteConfirm(null)}
              >
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton
                theme={theme}
                type="button"
                disabled={audienceBusyId === audienceDeleteConfirm.id}
                onClick={confirmDeleteAudience}
              >
                {audienceBusyId === audienceDeleteConfirm.id ? t('common.removing') : t('common.remove')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>
            {t('audiences.manage.deleteWarning', { count: audienceDeleteConfirm.member_count })}
          </EmptyStateText>
          <EmptyStateText theme={theme}>{t('common.irreversible')}</EmptyStateText>
        </Modal>
      )}

      {editingLead && (
        <Modal
          title={t('audiences.leads.editTitle', { phone: editingLead.phone || `#${editingLead.id}` })}
          onClose={() => !leadFormBusy && setEditingLead(null)}
          footer={
            <>
              <SecondaryButton
                theme={theme}
                type="button"
                disabled={leadFormBusy}
                onClick={() => setEditingLead(null)}
              >
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton
                theme={theme}
                type="button"
                disabled={leadFormBusy}
                onClick={handleSaveLead}
              >
                {leadFormBusy ? t('common.saving') : t('common.save')}
              </PrimaryButton>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Filter theme={theme}>
              {t('audiences.leads.columns.phone')}
              <TextInput
                theme={theme}
                type="text"
                value={leadForm.phone}
                onChange={(e) => setLeadForm((p) => ({ ...p, phone: e.target.value }))}
              />
            </Filter>
            <Filter theme={theme}>
              {t('audiences.leads.columns.name')}
              <TextInput
                theme={theme}
                type="text"
                value={leadForm.name}
                onChange={(e) => setLeadForm((p) => ({ ...p, name: e.target.value }))}
              />
            </Filter>
            <Filter theme={theme}>
              {t('audiences.leads.columns.status')}
              <Select
                theme={theme}
                value={leadForm.status}
                onChange={(e) => setLeadForm((p) => ({ ...p, status: e.target.value }))}
              >
                {CLIENT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`audiences.leads.statuses.${s}`)}
                  </option>
                ))}
              </Select>
            </Filter>
            <Filter theme={theme}>
              {t('audiences.leads.columns.country')}
              <TextInput
                theme={theme}
                type="text"
                value={leadForm.country}
                onChange={(e) => setLeadForm((p) => ({ ...p, country: e.target.value }))}
              />
            </Filter>
            <Filter theme={theme}>
              {t('audiences.leads.columns.language')}
              <TextInput
                theme={theme}
                type="text"
                value={leadForm.language}
                onChange={(e) => setLeadForm((p) => ({ ...p, language: e.target.value }))}
              />
            </Filter>
            <Filter theme={theme}>
              {t('audiences.leads.idleTimeout')}
              <TextInput
                theme={theme}
                type="number"
                min="10"
                placeholder={t('audiences.leads.idleTimeoutPlaceholder')}
                value={leadForm.idle_timeout_seconds}
                onChange={(e) => setLeadForm((p) => ({ ...p, idle_timeout_seconds: e.target.value }))}
              />
            </Filter>
          </div>
        </Modal>
      )}
    </PageContent>
  );
};

// Client CSV import result with accepted/rejected badges and phone/status/error list.
const ClientImportResult = ({ result, theme, t }) => (
  <>
    <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 600 }}>
        <span>{t('audiences.uploadResult.accepted')}</span>
        <Badge $color="#16a34a">{result.accepted}</Badge>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 600 }}>
        <span>{t('audiences.uploadResult.rejected')}</span>
        <Badge $color={result.rejected > 0 ? '#dc2626' : '#6b7280'}>{result.rejected}</Badge>
      </div>
    </div>
    <ResultTable theme={theme}>
      <thead>
        <tr>
          <th>{t('audiences.uploadResult.resultPhone')}</th>
          <th>{t('audiences.leads.columns.status')}</th>
          <th>{t('audiences.uploadResult.resultError')}</th>
        </tr>
      </thead>
      <tbody>
        {result.results.map((r, i) => (
          <tr key={i}>
            <td>{r.phone}</td>
            <td>
              {r.status ? (
                <Badge $color={statusColor(r.status, KINDS.CLIENT)}>
                  {t(`audiences.leads.statuses.${r.status}`) || r.status}
                </Badge>
              ) : (
                '—'
              )}
            </td>
            <td style={{ color: r.error ? '#dc2626' : undefined }}>{r.error ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </ResultTable>
  </>
);

// VOAD-34 lead table body: phone / name / status / audience / answered_calls /
// language / last_active / country (SClientRead), invalid/incomplete rows
// highlighted. Shared by main table and batch drill-down.
const LeadTable = ({ rows, theme, t, onRowClick, onEdit }) => (
  <TableContainer theme={theme}>
    <Table>
      <TableHeader theme={theme}>
        <tr>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.phone')}</TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.name')}</TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.status')}</TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.audience')}</TableHeaderCell>
          <TableHeaderCell theme={theme} $align="right">
            {t('audiences.leads.columns.answeredCalls')}
          </TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.language')}</TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.lastActive')}</TableHeaderCell>
          <TableHeaderCell theme={theme}>{t('audiences.leads.columns.country')}</TableHeaderCell>
          <TableHeaderCell theme={theme} $align="right">
            {t('audiences.leads.columns.actions')}
          </TableHeaderCell>
        </tr>
      </TableHeader>
      <tbody>
        {rows.map((row) => {
          const invalid = isInvalidLead(row);
          return (
            <LeadRow
              key={row.id}
              theme={theme}
              $invalid={invalid}
              onClick={() => onRowClick?.(row)}
              style={onRowClick ? { cursor: 'pointer' } : undefined}
            >
              <TableCell theme={theme}>
                {row.phone || '—'}
                {invalid && (
                  <Badge $color="#dc2626" style={{ marginLeft: 6 }}>
                    {t('audiences.leads.incomplete')}
                  </Badge>
                )}
              </TableCell>
              <TableCell theme={theme}>{row.name || '—'}</TableCell>
              <TableCell theme={theme}>
                {row.status ? (
                  <Badge $color={statusColor(row.status, KINDS.CLIENT)}>
                    {t(`audiences.leads.statuses.${row.status}`) || row.status.replace(/_/g, ' ')}
                  </Badge>
                ) : (
                  '—'
                )}
              </TableCell>
              <TableCell theme={theme}>
                {Array.isArray(row.audiences) && row.audiences.length > 0 ? row.audiences.join(', ') : '—'}
              </TableCell>
              <TableCell theme={theme} $align="right">{row.answered_calls ?? 0}</TableCell>
              <TableCell theme={theme}>{row.language || '—'}</TableCell>
              <TableCell theme={theme}>{formatDateTime(row.last_active)}</TableCell>
              <TableCell theme={theme}>{row.country || '—'}</TableCell>
              <TableCell
                theme={theme}
                $align="right"
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                {onEdit && (
                  <RowActionButton
                    theme={theme}
                    type="button"
                    onClick={() => onEdit(row)}
                  >
                    {t('audiences.leads.edit')}
                  </RowActionButton>
                )}
              </TableCell>
            </LeadRow>
          );
        })}
      </tbody>
    </Table>
  </TableContainer>
);
