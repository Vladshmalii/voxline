import { useEffect, useMemo, useState, useCallback } from 'react';
import styled, { keyframes } from 'styled-components';
import { HiArrowPath } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { PageContent, HeaderSection, PageTitle, HeaderActions, ContentScroll, SecondaryButton, TextInput, EmptyState, EmptyStateTitle, EmptyStateText, Segmented, SegmentOption } from 'components/ui';
import { KINDS, statusLabel, statusColor } from 'utils/statusMap';
import { TrendChart } from 'components/charts/TrendChart';
import { RadialStat } from 'components/charts/RadialStat';
import { HelpTip } from 'components/HelpTip';
import { statsApi } from 'utils/callApi';

// VOAD-38, extended per the reviewed plan (.lavish/dashboard-plan.html): the
// global snapshot (GET /stats/overview) still drives every breakdown below,
// reusing the app's existing status colors AND labels — every status/outcome/
// campaign-status/lead-status here is translated through the same
// utils/statusMap.js that StatusBadge/CampaignStatusBadge use elsewhere, so a label here
// reads the same in both languages as it does on the Calls/Campaigns/
// Audiences pages. On top of the original cut: a calls-per-day trend (GET
// /stats/timeseries, its own request so a range change doesn't re-fetch the
// whole snapshot), an answer-rate ring, and active/total agents.
//
// Deliberately NOT included: a per-agent "busiest agents" leaderboard
// (surfaces individual performance with no role/permission tiering — cut
// entirely, not just hidden), a leads-by-segment breakdown (segmentation was
// removed from the product), calls-by-sentiment and calls-by-direction
// (every call is outbound — direction/sentiment aren't product concepts here
// any more, same as on Calls/CallsPage).
//
// Design: only this app's own tokens (theme/colors.js, STATUS_COLORS, the
// existing card/button primitives from ui.js) — no borrowed brand system.
//
// Breakdown chart form is a labeled horizontal bar list, not a pie/donut
// (dataviz skill: part-to-whole compare-magnitude is bar's job, and every
// bar carries its own visible count as an accessibility fallback). Answer
// rate isn't part-to-whole across categories — it's a single proportion — so
// it gets a radial ring instead.
//
// Date range: presets (7/14/30/90 days) by default — this is a glance
// surface, not a filtered report — plus a "custom" option that reveals the
// same two `type="date"` inputs CampaignsPage already uses for
// created_from/created_to, so the one from/to idiom in this app stays one
// idiom.

const REASON_COLORS = [
  '#2563EB',
  '#EA580C',
  '#16A34A',
  '#D97706',
  '#DB2777',
  '#16A34A',
  '#6366F1',
];

const COMPLETED_COLOR = '#16A34A';
const AUTO_REFRESH_MS = 60_000;
const RANGE_PRESETS = [7, 14, 30, 90];

const prettify = (value) => String(value).replace(/_/g, ' ');

const numberFormatter = new Intl.NumberFormat();
const formatNumber = (n) => numberFormatter.format(n ?? 0);

const toIsoDate = (d) => d.toISOString().slice(0, 10);
const daysAgoIso = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toIsoDate(d);
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

const AutoToggle = styled(SecondaryButton)`
  ${({ $active, theme }) =>
    $active &&
    `
      border-color: ${theme.colors.accent};
      color: ${theme.colors.accent};
    `}
`;

const RangeGroup = Segmented;
const RangeOption = SegmentOption;

const CustomRange = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
`;

const CustomField = styled.label`
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};

  input {
    width: 140px;
  }
`;

const SectionEyebrow = styled.div`
  font-size: 12px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.muted};
  margin: 18px 0 8px;

  &:first-child {
    margin-top: 0;
  }
`;

const KpiGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
`;

const KpiTile = styled.div`
  padding: 8px 10px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`;

const KpiLabel = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  margin-bottom: 3px;
`;

const KpiValue = styled.div`
  font-size: 15px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  font-variant-numeric: proportional-nums;
`;

const KpiSub = styled.span`
  font-size: 12px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.muted};
`;

const ChartsGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 10px;
  align-items: start;
`;

const ChartCard = styled.div`
  padding: 12px 14px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const ChartTitle = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  margin-bottom: 8px;
`;

const BarRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
`;

const BarLabel = styled.div`
  width: 108px;
  flex-shrink: 0;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

const BarTrack = styled.div`
  flex: 1;
  height: 14px;
  background: ${({ theme }) => theme.colors.hover};
  border-radius: ${({ theme }) => theme.radii.xs};
  min-width: 0;
`;

const BarFill = styled.div`
  height: 100%;
  max-width: 100%;
  border-radius: 0 3px 3px 0;
  background: ${({ $color }) => $color};
`;

const BarValue = styled.div`
  width: 46px;
  flex-shrink: 0;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  font-variant-numeric: tabular-nums;
`;

const GeoTableEl = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
`;

const GeoTableHeadCell = styled.th`
  padding: 4px 6px;
  text-align: ${({ $align }) => $align || 'left'};
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const GeoTableCell = styled.td`
  padding: 5px 6px;
  text-align: ${({ $align }) => $align || 'left'};
  color: ${({ theme }) => theme.colors.primary};
  font-variant-numeric: tabular-nums;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

// GEO breakdown reads better as a table than a bar list — three numeric
// dimensions (campaigns, calls) per row rather than one value to compare
// magnitudes of.
const GeoTable = ({ rows, theme, t, emptyText }) => {
  if (rows.length === 0) {
    return <EmptyStateText theme={theme}>{emptyText}</EmptyStateText>;
  }
  return (
    <GeoTableEl>
      <thead>
        <tr>
          <GeoTableHeadCell theme={theme}>{t('dashboard.geo.country')}</GeoTableHeadCell>
          <GeoTableHeadCell theme={theme} $align="right">{t('dashboard.geo.campaigns')}</GeoTableHeadCell>
          <GeoTableHeadCell theme={theme} $align="right">{t('dashboard.geo.calls')}</GeoTableHeadCell>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key}>
            <GeoTableCell theme={theme}>{row.label}</GeoTableCell>
            <GeoTableCell theme={theme} $align="right">{formatNumber(row.campaigns)}</GeoTableCell>
            <GeoTableCell theme={theme} $align="right">{formatNumber(row.calls)}</GeoTableCell>
          </tr>
        ))}
      </tbody>
    </GeoTableEl>
  );
};

/** A labeled horizontal bar per item, sorted by the caller — see module docstring for why bar, not pie. */
const BarList = ({ items, theme, emptyText }) => {
  if (items.length === 0) {
    return <EmptyStateText theme={theme}>{emptyText}</EmptyStateText>;
  }
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div>
      {items.map((item) => (
        <BarRow key={item.key} title={`${item.label}: ${formatNumber(item.value)}`}>
          <BarLabel theme={theme}>{item.label}</BarLabel>
          <BarTrack theme={theme}>
            <BarFill $color={item.color} style={{ width: `${(item.value / max) * 100}%` }} />
          </BarTrack>
          <BarValue theme={theme}>{formatNumber(item.value)}</BarValue>
        </BarRow>
      ))}
    </div>
  );
};

const sortDesc = (rows) => [...rows].sort((a, b) => b.value - a.value);

export const DashboardPage = () => {
  const { theme } = useTheme();
  const { t, locale } = useI18n();

  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const [geo, setGeo] = useState(null);
  const [geoError, setGeoError] = useState(null);

  const [rangePreset, setRangePreset] = useState(30);
  const [customFrom, setCustomFrom] = useState(daysAgoIso(29));
  const [customTo, setCustomTo] = useState(daysAgoIso(0));
  const [trend, setTrend] = useState(null);
  const [trendError, setTrendError] = useState(null);

  const { dateFrom, dateTo } = useMemo(() => {
    if (rangePreset === 'custom') {
      return { dateFrom: customFrom, dateTo: customTo };
    }
    return { dateFrom: daysAgoIso(rangePreset - 1), dateTo: daysAgoIso(0) };
  }, [rangePreset, customFrom, customTo]);

  const load = useCallback(({ keepStats = false } = {}) => {
    if (!keepStats) setStats(null);
    setRefreshing(true);
    setError(null);
    statsApi
      .overview()
      .then((data) => setStats(data))
      .catch((e) => setError(e.message))
      .finally(() => setRefreshing(false));
  }, []);

  const loadTrend = useCallback((from, to) => {
    if (!from || !to || from > to) return;
    statsApi
      .timeseries(from, to)
      .then((data) => {
        setTrend(data.days);
        setTrendError(null);
      })
      .catch((e) => setTrendError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadTrend(dateFrom, dateTo);
  }, [loadTrend, dateFrom, dateTo]);

  useEffect(() => {
    statsApi
      .activeGeo()
      .then((data) => setGeo(data.countries))
      .catch((e) => setGeoError(e.message));
  }, []);

  const reload = () => {
    load({ keepStats: true });
    loadTrend(dateFrom, dateTo);
  };

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = setInterval(reload, AUTO_REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, dateFrom, dateTo]);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale === 'ru' ? 'ru-RU' : 'en-US', {
        month: 'short',
        day: 'numeric',
      }),
    [locale]
  );
  const dateFormatterShort = useMemo(
    () => new Intl.DateTimeFormat(locale === 'ru' ? 'ru-RU' : 'en-US', { day: 'numeric' }),
    [locale]
  );
  const formatDate = (iso) => dateFormatter.format(new Date(iso));
  const formatDateShort = (iso) => dateFormatterShort.format(new Date(iso));

  const formatDuration = (seconds) => {
    if (seconds == null) return '—';
    return t('dashboard.duration', { seconds: Math.round(seconds) });
  };

  const formatPercent = (ratio) => (ratio == null ? '—' : `${Math.round(ratio * 100)}%`);

  const runningCampaigns = stats?.campaigns.by_status.find((s) => s.status === 'running')?.count ?? 0;

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('channelStats.callsTitle')}</PageTitle>
        <HeaderActions>
          <RangeGroup theme={theme}>
            {RANGE_PRESETS.map((opt) => (
              <RangeOption
                key={opt}
                theme={theme}
                type="button"
                $active={rangePreset === opt}
                onClick={() => setRangePreset(opt)}
              >
                {t(`dashboard.range.${opt}`)}
              </RangeOption>
            ))}
            <RangeOption
              theme={theme}
              type="button"
              $active={rangePreset === 'custom'}
              onClick={() => setRangePreset('custom')}
            >
              {t('dashboard.range.custom')}
            </RangeOption>
          </RangeGroup>
          {rangePreset === 'custom' && (
            <CustomRange>
              <CustomField theme={theme}>
                {t('dashboard.range.from')}
                <TextInput
                  theme={theme}
                  type="date"
                  value={customFrom}
                  max={customTo}
                  onChange={(e) => setCustomFrom(e.target.value)}
                />
              </CustomField>
              <CustomField theme={theme}>
                {t('dashboard.range.to')}
                <TextInput
                  theme={theme}
                  type="date"
                  value={customTo}
                  min={customFrom}
                  max={daysAgoIso(0)}
                  onChange={(e) => setCustomTo(e.target.value)}
                />
              </CustomField>
            </CustomRange>
          )}
          <AutoToggle
            theme={theme}
            type="button"
            $active={autoRefresh}
            onClick={() => setAutoRefresh((v) => !v)}
            title={t('dashboard.autoRefresh')}
          >
            {t('dashboard.autoRefresh')}
          </AutoToggle>
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
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        {stats === null ? (
          error ? (
            <EmptyState theme={theme}>
              <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
              <EmptyStateText theme={theme}>{error}</EmptyStateText>
            </EmptyState>
          ) : (
            <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
          )
        ) : (
          <>
            <SectionEyebrow theme={theme}>{t('dashboard.sections.overview')}</SectionEyebrow>
            <KpiGrid>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.totalCalls')}
                    <HelpTip text={t('dashboard.help.totalCalls')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>{formatNumber(stats.calls.total)}</KpiValue>
                </div>
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.callsToday')}
                    <HelpTip text={t('dashboard.help.callsToday')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>{formatNumber(stats.calls.today)}</KpiValue>
                </div>
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.answerRate')}
                    <HelpTip text={t('dashboard.help.answerRate')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>{formatPercent(stats.calls.answer_rate)}</KpiValue>
                </div>
                <RadialStat theme={theme} ratio={stats.calls.answer_rate} />
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.avgDuration')}
                    <HelpTip text={t('dashboard.help.avgDuration')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>{formatDuration(stats.calls.avg_duration_seconds)}</KpiValue>
                </div>
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.runningCampaigns')}
                    <HelpTip text={t('dashboard.help.runningCampaigns')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>
                    {formatNumber(runningCampaigns)}
                    <KpiSub theme={theme}> / {formatNumber(stats.campaigns.total)}</KpiSub>
                  </KpiValue>
                </div>
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.activeAgents')}
                    <HelpTip text={t('dashboard.help.activeAgents')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>
                    {formatNumber(stats.agents.active)}
                    <KpiSub theme={theme}> / {formatNumber(stats.agents.total)}</KpiSub>
                  </KpiValue>
                </div>
              </KpiTile>
              <KpiTile theme={theme}>
                <div>
                  <KpiLabel theme={theme}>
                    {t('dashboard.kpi.totalLeads')}
                    <HelpTip text={t('dashboard.help.totalLeads')} />
                  </KpiLabel>
                  <KpiValue theme={theme}>{formatNumber(stats.clients.total)}</KpiValue>
                </div>
              </KpiTile>
            </KpiGrid>

            <SectionEyebrow theme={theme}>{t('dashboard.sections.trend')}</SectionEyebrow>
            <ChartCard theme={theme}>
              <ChartTitle theme={theme}>{t('dashboard.charts.callsTrend')}</ChartTitle>
              {trendError ? (
                <EmptyStateText theme={theme}>{trendError}</EmptyStateText>
              ) : trend === null ? (
                <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
              ) : trend.length === 0 ? (
                <EmptyStateText theme={theme}>{t('dashboard.noData')}</EmptyStateText>
              ) : (
                <TrendChart
                  theme={theme}
                  data={trend}
                  totalColor={theme.colors.accent}
                  completedColor={COMPLETED_COLOR}
                  failedColor="#DC2626"
                  totalLabel={t('dashboard.charts.callsTrendTotal')}
                  completedLabel={t('dashboard.charts.callsTrendCompleted')}
                  failedLabel={t('dashboard.charts.callsTrendFailed')}
                  formatDate={formatDate}
                  formatDateShort={formatDateShort}
                />
              )}
            </ChartCard>

            <SectionEyebrow theme={theme}>{t('dashboard.sections.breakdown')}</SectionEyebrow>
            <ChartsGrid>
              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.callsByStatus')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={sortDesc(
                    stats.calls.by_status.map((row) => ({
                      key: row.status,
                      label: statusLabel(t, row.status, KINDS.CALL),
                      value: row.count,
                      color: statusColor(row.status, KINDS.CALL),
                    }))
                  )}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.callsByOutcome')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={sortDesc(
                    stats.calls.by_outcome.map((row) => ({
                      key: row.outcome,
                      label: statusLabel(t, row.outcome, KINDS.OUTCOME),
                      value: row.count,
                      color: statusColor(row.outcome, KINDS.OUTCOME),
                    }))
                  )}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.declineReasons')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={sortDesc(
                    stats.calls.by_reason_category.map((row, i) => ({
                      key: row.reason_category,
                      label: (() => {
                        const key = `calls.reasonCategories.${row.reason_category}`;
                        const label = t(key);
                        return label && label !== key ? label : prettify(row.reason_category);
                      })(),
                      value: row.count,
                      color: REASON_COLORS[i % REASON_COLORS.length],
                    }))
                  )}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.campaignsByStatus')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={sortDesc(
                    stats.campaigns.by_status.map((row) => ({
                      key: row.status,
                      label: statusLabel(t, row.status, KINDS.CAMPAIGN),
                      value: row.count,
                      color: statusColor(row.status, KINDS.CAMPAIGN),
                    }))
                  )}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.topCampaigns')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={stats.campaigns.top_by_calls.map((row) => ({
                    key: row.campaign_id,
                    label: row.name,
                    value: row.calls,
                    color: theme.colors.accentNeon,
                  }))}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.activeGeo')}</ChartTitle>
                <GeoTable
                  theme={theme}
                  t={t}
                  emptyText={geoError || t('dashboard.noData')}
                  rows={(geo || []).map((row, i) => ({
                    key: row.country || `unknown-${i}`,
                    label: row.country || t('dashboard.unknownGeo'),
                    campaigns: row.campaigns,
                    calls: row.calls,
                  }))}
                />
              </ChartCard>

              <ChartCard theme={theme}>
                <ChartTitle theme={theme}>{t('dashboard.charts.leadsByStatus')}</ChartTitle>
                <BarList
                  theme={theme}
                  emptyText={t('dashboard.noData')}
                  items={sortDesc(
                    stats.clients.by_status.map((row) => {
                      return {
                        key: row.status,
                        label: statusLabel(t, row.status, KINDS.CLIENT),
                        value: row.count,
                        color: statusColor(row.status, KINDS.CLIENT),
                      };
                    })
                  )}
                />
              </ChartCard>
            </ChartsGrid>
          </>
        )}
      </ContentScroll>
    </PageContent>
  );
};
