import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import styled from 'styled-components';
import { HiArrowPath, HiChevronDown, HiAdjustmentsHorizontal, HiXMark } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { StatusBadge } from 'components/badges';
import { KINDS } from 'utils/statusMap';
import { Modal } from 'components/Modal';
import { Pagination } from 'components/Pagination';
import { toast } from 'components/Toaster';
import { HistoryExport } from 'components/HistoryExport';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
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
import { smsApi, messagingApi, agentsApi, campaignsApi } from 'utils/callApi';
import { useUser } from 'contexts/UserContext';
import { canSendSms, hasFullAccess } from 'utils/permissions';
import { PERIODS, periodRange, historyDateQuery, loadFilterOptions } from 'utils/historyFilters';
import {
  FilterCard, FilterHeader, FilterGrid, Filter, SearchFilter, StatusFilter,
  PeriodBar, PeriodButton, FilterNote, AdvancedToggle, AdvancedGrid,
  Chips, Chip, ResultsBar, RefreshButton,
} from 'components/HistoryFilters';

// SMS is sent and re-read, never edited, so like CallsPage this mirrors
// CrudPage's chrome by hand: no filters, server-side paging or detail view on
// CrudPage would fit. The list answers with SMessageListRead ({ data, count }).
const PAGE_SIZE = 50;

// MessageStatusEnum, verbatim.
const STATUSES = ['queued', 'sent', 'delivered', 'undelivered', 'failed', 'canceled'];

const EMPTY_TEXT = { search: '', to_search: '', sender: '', call_id: '' };
const EMPTY_FILTERS = {
  ...EMPTY_TEXT, messaging_id: '', status: '', agent_id: '', campaign_id: '',
  date_from: '', date_to: '', source: '', sort: 'newest',
};
const AgentCell = styled.div`
  min-width: 100px;
  small { display: block; color: ${({ theme }) => theme.colors.secondary}; margin-top: 4px; font-size: 12px; }
`;

const DetailGrid = styled.div`
  display: grid;
  grid-template-columns: minmax(120px, max-content) 1fr;
  gap: 10px 16px;
  align-items: baseline;
`;

const DetailKey = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
`;

const DetailValue = styled.div`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  word-break: break-word;
  white-space: pre-wrap;
`;

const BodyCell = styled.div`
  min-width: 180px;
  max-width: 360px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
`;

// SSmsSend. `messaging_id` blank uses the organization's single active route.
// Sender and route are admin-only — clients never see or pick them.
const sendFields = (routes, fullAccess) => [
  { name: 'to', labelKey: 'sms.fields.to', type: 'text', required: true, placeholderKey: 'sms.filters.toPlaceholder' },
  { name: 'body', labelKey: 'sms.fields.body', type: 'textarea', required: true, rows: 4 },
  ...(fullAccess ? [{
    name: 'sender',
    labelKey: 'sms.fields.sender',
    type: 'text',
    nullable: true,
    hintKey: 'sms.fields.senderHint',
  }, {
    name: 'messaging_id',
    labelKey: 'sms.fields.messagingId',
    type: 'select',
    asNumber: true,
    nullable: true,
    hintKey: 'sms.fields.messagingIdHint',
    options: (routes || []).map((r) => ({ value: r.id, label: `${r.name} (#${r.id})` })),
  }] : []),
];

export const SmsPage = () => {
  const { theme } = useTheme();
  const { t, locale } = useI18n();
  const user = useUser();
  const canSend = canSendSms(user?.role);
  const fullAccess = hasFullAccess(user?.role);

  const [routes, setRoutes] = useState([]);
  const [agents, setAgents] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [lookupError, setLookupError] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [textInputs, setTextInputs] = useState(EMPTY_TEXT);
  const [advanced, setAdvanced] = useState(false);
  const requestId = useRef(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [detail, setDetail] = useState(null); // { id, data?, error? }

  const [sending, setSending] = useState(false);
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let canceled = false;
    setLookupError(false);
    const lookups = [[agentsApi, setAgents], [campaignsApi, setCampaigns, { include_archived: true }]];
    if (hasFullAccess(user?.role)) lookups.push([messagingApi, setRoutes]);
    Promise.allSettled(lookups.map(async ([api, update, query]) => {
      const data = await loadFilterOptions(api, query, () => canceled);
      if (!canceled) update(data);
    })).then((results) => {
      if (!canceled) setLookupError(results.some((result) => result.status === 'rejected'));
    });
    return () => { canceled = true; };
  }, [user?.role]);

  // Text searches apply together after a short pause; selections apply immediately.
  useEffect(() => {
    const values = Object.fromEntries(Object.entries(textInputs).map(([key, value]) => [key, value.trim()]));
    if (Object.keys(values).every((key) => filters[key] === values[key])) return;
    const timer = setTimeout(() => {
      setFilters((prev) => Object.keys(values).some((key) => prev[key] !== values[key]) ? { ...prev, ...values } : prev);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [textInputs, filters]);

  const invalidRange = filters.date_from && filters.date_to && filters.date_to < filters.date_from;
  const invalidCall = textInputs.call_id !== '' && !/^[1-9]\d*$/.test(textInputs.call_id.trim());
  const invalidFilters = invalidRange || invalidCall;

  const routeById = useMemo(() => new Map(routes.map((r) => [r.id, r])), [routes]);
  const routeLabel = useCallback(
    (id) => {
      if (id === null || id === undefined) return '—';
      const r = routeById.get(id);
      return r ? r.name : `#${id}`;
    },
    [routeById]
  );

  const fetchMessages = useCallback(
    ({ keepRows = false } = {}) => {
      const currentRequest = ++requestId.current;
      if (invalidFilters) { setRefreshing(false); return; }
      if (!keepRows) setRows(null);
      setRefreshing(true);
      setLoadError(null);
      smsApi
        .list({ ...historyDateQuery(filters, !fullAccess), limit: pageSize, offset })
        .then((res) => {
          if (currentRequest !== requestId.current) return;
          setRows(Array.isArray(res?.data) ? res.data : []);
          setTotal(res?.count ?? 0);
        })
        .catch((e) => {
          if (currentRequest !== requestId.current) return;
          setLoadError(e.message);
          setRows([]);
          setTotal(0);
        })
        .finally(() => { if (currentRequest === requestId.current) setRefreshing(false); });
    },
    [filters, offset, pageSize, invalidFilters, fullAccess]
  );

  const changePageSize = (size) => {
    setOffset(0);
    setPageSize(size);
  };

  useEffect(() => {
    fetchMessages();
    return () => { requestId.current += 1; };
  }, [fetchMessages]);

  const reload = () => fetchMessages({ keepRows: true });

  const setFilter = (key, value) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, [key]: value }));
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
  const agentLabel = (row) => row.agent_name || (row.agent_id ? `#${row.agent_id}` : t(row.call_id ? 'sms.noAgent' : 'sms.sources.manual'));

  const openDetail = async (id) => {
    setDetail({ id });
    try {
      const data = await smsApi.get(id);
      setDetail((prev) => prev?.id === id ? { id, data } : prev);
    } catch (e) {
      setDetail((prev) => prev?.id === id ? { id, error: e.message } : prev);
    }
  };

  const openSend = () => {
    setFormValues(buildInitialValues(sendFields(routes, hasFullAccess(user?.role)), null));
    setFormErrors({});
    setSending(true);
  };

  const submitSend = async () => {
    const fields = sendFields(routes, hasFullAccess(user?.role));
    const { payload, errors } = buildPayload(fields, formValues);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      const created = await smsApi.send(payload);
      toast(t('sms.sent', { id: created.id }), 'success');
      setSending(false);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const activeFilters = Object.entries(filters).filter(([key, value]) => key !== 'sort' && value !== '');
  const filtersDirty = activeFilters.length > 0 || Object.values(textInputs).some(Boolean) || filters.sort !== 'newest';
  const advancedCount = ['messaging_id', 'campaign_id', 'sender', 'call_id', 'source'].filter((key) => filters[key]).length;
  const filterValue = (key, value) => {
    if (key === 'date_from' || key === 'date_to') return value.replace('T', ' ');
    if (key === 'status') return t(`sms.statuses.${value}`);
    if (key === 'source') return t(`sms.sources.${value}`);
    const options = { messaging_id: routes, agent_id: agents, campaign_id: campaigns }[key];
    return options ? options.find((item) => String(item.id) === value)?.name || `#${value}` : value;
  };

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('sms.title')}</PageTitle>
        <HeaderActions>
          {canSend && (
            <PrimaryButton theme={theme} type="button" onClick={openSend}>
              + {t('sms.send')}
            </PrimaryButton>
          )}
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        <FilterCard theme={theme}>
          <FilterHeader theme={theme}>
            <h3><HiAdjustmentsHorizontal />{t('sms.filters.title')}</h3>
            <HeaderActions>
              <HistoryExport
                name="sms"
                disabled={Boolean(invalidFilters) || refreshing || Boolean(loadError)}
                empty={total === 0}
                onExport={(format) => smsApi.export(historyDateQuery(filters, !fullAccess), format)}
              />
              {filtersDirty && <SecondaryButton theme={theme} type="button" onClick={resetFilters}>{t('sms.filters.reset')}</SecondaryButton>}
              <RefreshButton theme={theme} type="button" $busy={refreshing} disabled={refreshing || Boolean(invalidFilters)} onClick={reload} title={t('sms.filters.refresh')} aria-label={t('sms.filters.refresh')}>
                <HiArrowPath />
              </RefreshButton>
            </HeaderActions>
          </FilterHeader>
          <PeriodBar>
            {PERIODS.map((period) => <PeriodButton key={period} type="button" theme={theme} $active={activePeriod === period} aria-pressed={activePeriod === period} onClick={() => setPeriod(period)}>{t(`sms.periods.${period}`)}</PeriodButton>)}
            <FilterNote theme={theme}>{t(fullAccess ? 'sms.filters.dateHint' : 'sms.filters.dateTimeHint')}</FilterNote>
          </PeriodBar>
          <FilterGrid>
            <SearchFilter theme={theme}>
              {t('sms.filters.search')}
              <TextInput theme={theme} type="search" value={textInputs.search} maxLength={1600} placeholder={t('sms.filters.searchPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, search: e.target.value }))} />
            </SearchFilter>
            <Filter theme={theme}>
              {t('sms.filters.to_search')}
              <TextInput theme={theme} type="search" value={textInputs.to_search} maxLength={128} placeholder={t('sms.filters.numberPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, to_search: e.target.value }))} />
            </Filter>
            <Filter theme={theme}>
              {t('sms.filters.agent_id')}
              <Select theme={theme} value={filters.agent_id} onChange={(e) => setFilter('agent_id', e.target.value)}>
                <option value="">{t('sms.filters.all')}</option>
                {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} (#{agent.id})</option>)}
              </Select>
            </Filter>
            <StatusFilter theme={theme}>
              {t('sms.filters.status')}
              <Select theme={theme} value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
                <option value="">{t('sms.filters.all')}</option>
                {STATUSES.filter((status) => fullAccess || !['queued', 'sent', 'failed'].includes(status)).map((status) => <option key={status} value={status}>{t(`sms.statuses.${status}`)}</option>)}
              </Select>
            </StatusFilter>
            <Filter theme={theme}>
              {t('sms.filters.date_from')}
              <TextInput theme={theme} type={fullAccess ? "date" : "datetime-local"} value={filters.date_from} max={filters.date_to || undefined} aria-invalid={Boolean(invalidRange)} onChange={(e) => setFilter('date_from', e.target.value)} />
            </Filter>
            <Filter theme={theme}>
              {t('sms.filters.date_to')}
              <TextInput theme={theme} type={fullAccess ? "date" : "datetime-local"} value={filters.date_to} min={filters.date_from || undefined} aria-invalid={Boolean(invalidRange)} onChange={(e) => setFilter('date_to', e.target.value)} />
            </Filter>
          </FilterGrid>
          <AdvancedToggle theme={theme} type="button" $open={advanced} aria-expanded={advanced} aria-controls="sms-advanced-filters" onClick={() => setAdvanced((prev) => !prev)}>
            {t('sms.filters.advanced')}{advancedCount > 0 && ` (${advancedCount})`} <HiChevronDown />
          </AdvancedToggle>
          {advanced && <AdvancedGrid theme={theme} id="sms-advanced-filters">
            {hasFullAccess(user?.role) && <Filter theme={theme}>
              {t('sms.filters.messaging_id')}
              <Select theme={theme} value={filters.messaging_id} onChange={(e) => setFilter('messaging_id', e.target.value)}>
                <option value="">{t('sms.filters.all')}</option>
                {routes.map((route) => <option key={route.id} value={route.id}>{route.name} (#{route.id})</option>)}
              </Select>
            </Filter>}
            <Filter theme={theme}>
              {t('sms.filters.campaign_id')}
              <Select theme={theme} value={filters.campaign_id} onChange={(e) => setFilter('campaign_id', e.target.value)}>
                <option value="">{t('sms.filters.all')}</option>
                {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name} (#{campaign.id})</option>)}
              </Select>
            </Filter>
            {hasFullAccess(user?.role) && <Filter theme={theme}>
              {t('sms.filters.sender')}
              <TextInput theme={theme} type="search" value={textInputs.sender} maxLength={128} placeholder={t('sms.filters.senderPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, sender: e.target.value }))} />
            </Filter>}
            {fullAccess && <Filter theme={theme}>
              {t('sms.filters.source')}
              <Select theme={theme} value={filters.source} onChange={(e) => setFilter('source', e.target.value)}>
                <option value="">{t('sms.filters.all')}</option>
                <option value="call">{t('sms.sources.call')}</option>
                <option value="manual">{t('sms.sources.manual')}</option>
              </Select>
            </Filter>}
            <Filter theme={theme}>
              {t('sms.filters.call_id')}
              <TextInput theme={theme} type="text" inputMode="numeric" pattern="[0-9]*" value={textInputs.call_id} aria-invalid={invalidCall} placeholder={t('sms.filters.callPlaceholder')} onChange={(e) => setTextInputs((prev) => ({ ...prev, call_id: e.target.value }))} />
            </Filter>
          </AdvancedGrid>}
          {lookupError && <EmptyStateText theme={theme} role="status">{t('sms.filters.lookupError')}</EmptyStateText>}
          {activeFilters.length > 0 && <Chips>
            {activeFilters.map(([key, value]) => <Chip key={key} type="button" theme={theme} onClick={() => removeFilter(key)} aria-label={t('sms.filters.remove', { filter: t(`sms.filters.${key}`) })} title={`${t(`sms.filters.${key}`)}: ${filterValue(key, value)}`}>
              <span>{t(`sms.filters.${key}`)}: {filterValue(key, value)}</span><HiXMark />
            </Chip>)}
          </Chips>}
        </FilterCard>
        <ResultsBar theme={theme}>
          <span role="status" aria-live="polite">{t('sms.results', { count: invalidFilters || refreshing || loadError ? '—' : new Intl.NumberFormat(locale).format(total) })}</span>
          <label>{t('sms.filters.sort')}
            <Select theme={theme} value={filters.sort} onChange={(e) => setFilter('sort', e.target.value)}>
              <option value="newest">{t('sms.filters.newest')}</option>
              <option value="oldest">{t('sms.filters.oldest')}</option>
            </Select>
          </label>
        </ResultsBar>

        {invalidFilters ? (
          <EmptyState theme={theme}><EmptyStateText theme={theme} role="alert">{t(invalidRange ? 'sms.filters.invalidRange' : 'sms.filters.invalidCall')}</EmptyStateText></EmptyState>
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
            <EmptyStateText theme={theme}>{t('sms.empty')}</EmptyStateText>
          </EmptyState>
        ) : (
          <>
            <TableContainer theme={theme}>
              <Table>
                <TableHeader theme={theme}>
                  <tr>
                    <TableHeaderCell theme={theme}>{t('common.id')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('common.status')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('sms.columns.agent')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('sms.columns.to')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('sms.columns.body')}</TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="center">
                      {t('sms.columns.segments')}
                    </TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('sms.columns.created')}</TableHeaderCell>
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
                        <StatusBadge kind={KINDS.SMS} value={row.status} />
                      </TableCell>
                      <TableCell theme={theme}>
                        <AgentCell theme={theme}>{agentLabel(row)}{row.call_id && <small>{t('sms.call', { id: row.call_id })}</small>}</AgentCell>
                      </TableCell>
                      <TableCell theme={theme}>{row.to_number}</TableCell>
                      <TableCell theme={theme}>
                        <BodyCell title={row.body}>{row.body}</BodyCell>
                      </TableCell>
                      <TableCell theme={theme} $align="center">
                        {row.segments}
                      </TableCell>
                      <TableCell theme={theme}>{formatDateTime(row.created_at)}</TableCell>
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
        <Modal title={t('sms.detail.title', { id: detail.id })} onClose={() => setDetail(null)} wide>
          {detail.error ? (
            <EmptyStateText theme={theme}>{detail.error}</EmptyStateText>
          ) : !detail.data ? (
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
          ) : (
            <SmsDetail data={detail.data} theme={theme} t={t} routeLabel={routeLabel} agentLabel={agentLabel} showAdminFields={hasFullAccess(user?.role)} />
          )}
        </Modal>
      )}

      {sending && (
        <Modal
          title={t('sms.sendTitle')}
          onClose={() => setSending(false)}
          wide
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setSending(false)}>
                {t('common.cancel')}
              </SecondaryButton>
              <PrimaryButton theme={theme} type="button" disabled={submitting} onClick={submitSend}>
                {submitting ? t('common.saving') : t('sms.send')}
              </PrimaryButton>
            </>
          }
        >
          <ResourceForm
            fields={sendFields(routes, hasFullAccess(user?.role))}
            values={formValues}
            errors={formErrors}
            onChange={setFormValues}
          />
        </Modal>
      )}
    </PageContent>
  );
};

const SmsDetail = ({ data, theme, t, routeLabel, agentLabel, showAdminFields }) => {
  const Field = ({ label, children }) => (
    <>
      <DetailKey theme={theme}>{label}</DetailKey>
      <DetailValue theme={theme}>{children}</DetailValue>
    </>
  );

  return (
    <DetailGrid>
      <Field label={t('sms.detail.status')}>
        <StatusBadge kind={KINDS.SMS} value={data.status} />
      </Field>
      {showAdminFields && <Field label={t('sms.detail.route')}>{routeLabel(data.messaging_id)}</Field>}
      <Field label={t('sms.detail.agent')}>{agentLabel(data)}</Field>
      <Field label={t('sms.detail.source')}>{t(data.call_id ? 'sms.sources.call' : 'sms.sources.manual')}</Field>
      {data.call_id && <Field label={t('sms.detail.call')}>#{data.call_id}</Field>}
      <Field label={t('sms.detail.created')}>{formatDateTime(data.created_at)}</Field>
      <Field label={t('sms.detail.to')}>{data.to_number}</Field>
      {showAdminFields && <Field label={t('sms.detail.from')}>{data.sender ?? '—'}</Field>}
      <Field label={t('sms.detail.segments')}>{data.segments}</Field>
      <Field label={t('sms.detail.body')}>{data.body}</Field>
      {data.provider_ref && <Field label={t('sms.detail.providerRef')}>{data.provider_ref}</Field>}
      {data.error && (
        <Field label={t('sms.detail.error')}>
          <span style={{ color: '#DC2626' }}>{data.error}</span>
        </Field>
      )}
      <Field label={t('sms.detail.sent')}>{formatDateTime(data.sent_at)}</Field>
      <Field label={t('sms.detail.settled')}>{formatDateTime(data.settled_at)}</Field>
      <Field label={t('sms.detail.uuid')}>{data.uuid}</Field>
    </DetailGrid>
  );
};
