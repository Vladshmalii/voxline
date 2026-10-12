import { useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';
import { FiRefreshCw } from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { hasFullAccess } from 'utils/permissions';
import { smsApi, messagingApi, MAX_PAGE } from 'utils/callApi';
import { HelpTip } from 'components/HelpTip';
import { TrendChart } from 'components/charts/TrendChart';
import {
  PageContent, HeaderSection, PageTitle, HeaderActions, ContentScroll, Card,
  SecondaryButton, Select, TextInput, EmptyState, EmptyStateText,
} from 'components/ui';
import { KINDS, statusColor } from 'utils/statusMap';

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
  @media (max-width: 1100px) { grid-template-columns: repeat(2, minmax(140px, 1fr)); }
  @media (max-width: 600px) { grid-template-columns: 1fr; }
`;
const Tile = styled(Card)`
  padding: 16px;
`;
const Label = styled.div`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
  margin-bottom: 8px;
`;
const Value = styled.div`
  font-size: 25px;
  font-weight: 650;
  color: ${({ theme }) => theme.colors.primary};
  font-variant-numeric: tabular-nums;
`;
const SectionTitle = styled.h3`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 16px;
`;
const ChartHeader = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
  h3 { margin: 0; }
`;
const Controls = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  input { width: 145px; }
`;
const DateField = styled.label`
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;
const StatusRow = styled.div`
  display: grid;
  grid-template-columns: 130px minmax(40px, 1fr) 60px;
  gap: 12px;
  align-items: center;
  margin: 12px 0;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.primary};
  strong { text-align: right; font-variant-numeric: tabular-nums; }
`;
const Track = styled.div`
  height: 10px;
  border-radius: 8px;
  overflow: hidden;
  background: ${({ theme }) => theme.colors.hover};
`;
const Fill = styled.div`
  height: 100%;
  border-radius: inherit;
  width: ${({ $width }) => $width}%;
  background: ${({ $color }) => $color};
  transition: width 250ms ease;
  @media (prefers-reduced-motion: reduce) { transition: none; }
`;
const daysAgo = (offset) => {
  const day = new Date();
  day.setUTCDate(day.getUTCDate() - offset);
  return day.toISOString().slice(0, 10);
};

export const SmsStatsPage = () => {
  const { theme } = useTheme();
  const { t, locale } = useI18n();
  const user = useUser();
  const fullAccess = hasFullAccess(user?.role);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(null);
  const [trendError, setTrendError] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [routes, setRoutes] = useState([]);
  const [route, setRoute] = useState('');
  const [preset, setPreset] = useState('30');
  const [customFrom, setCustomFrom] = useState(daysAgo(29));
  const [customTo, setCustomTo] = useState(daysAgo(0));
  const [overviewBusy, setOverviewBusy] = useState(false);
  const [trendBusy, setTrendBusy] = useState(false);
  const from = preset === 'custom' ? customFrom : daysAgo(Number(preset) - 1);
  const to = preset === 'custom' ? customTo : daysAgo(0);
  const formatNumber = (value) => new Intl.NumberFormat(locale).format(value);
  const formatDate = (value) => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(value));
  const query = useMemo(() => ({ messaging_id: route }), [route]);

  useEffect(() => {
    if (!hasFullAccess(user?.role)) return;
    let canceled = false;
    messagingApi.list({ limit: MAX_PAGE }).then((res) => {
      if (!canceled) setRoutes(Array.isArray(res) ? res : []);
    }).catch(() => undefined);
    return () => { canceled = true; };
  }, [user?.role]);

  useEffect(() => {
    let canceled = false;
    setOverviewBusy(true);
    setStats(null);
    setError(null);
    smsApi.overview(query).then((res) => { if (!canceled) setStats(res); })
      .catch((err) => { if (!canceled) setError(err.message); })
      .finally(() => { if (!canceled) setOverviewBusy(false); });
    return () => { canceled = true; };
  }, [query, refresh]);

  useEffect(() => {
    let canceled = false;
    setDays(null);
    setTrendError(null);
    const span = (new Date(to) - new Date(from)) / 86400000;
    if (!from || !to || !Number.isFinite(span) || span < 0 || span > 89) {
      setTrendError(t('channelStats.rangeError'));
      setTrendBusy(false);
      return;
    }
    setTrendBusy(true);
    smsApi.timeseries(from, to, query).then((res) => { if (!canceled) setDays(res.days || []); })
      .catch((err) => { if (!canceled) setTrendError(err.message); })
      .finally(() => { if (!canceled) setTrendBusy(false); });
    return () => { canceled = true; };
  }, [from, to, query, refresh, t]);

  const metrics = ['total', 'today', 'sent', 'delivered', 'errors', 'pending', 'segments', 'deliveryRate']
    .filter((key) => fullAccess || !['sent', 'errors', 'deliveryRate'].includes(key));
  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('channelStats.title')}</PageTitle>
        <HeaderActions>
          {routes.length > 0 && <Select theme={theme} style={{ width: 'auto', minWidth: 180 }} value={route} aria-label={t('sms.filters.route')} onChange={(event) => setRoute(event.target.value)}>
            <option value="">{t('channelStats.allRoutes')}</option>
            {routes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>}
          <SecondaryButton theme={theme} disabled={overviewBusy || trendBusy} onClick={() => setRefresh((value) => value + 1)}
            aria-label={t('sms.filters.refresh')}><FiRefreshCw />{t('sms.filters.refresh')}</SecondaryButton>
        </HeaderActions>
      </HeaderSection>
      <ContentScroll theme={theme}>
        <SectionTitle theme={theme}>{t('channelStats.overview')}</SectionTitle>
        {error ? <EmptyStateText theme={theme}>{error}</EmptyStateText> : stats === null ?
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState> : <>
            <Grid>{metrics.map((key) => <Tile key={key} theme={theme}>
              <Label theme={theme}>{t(`channelStats.${key}`)}
                {key === 'deliveryRate' && <HelpTip text={t('channelStats.deliveryHelp')} />}
                {key === 'sent' && <HelpTip text={t('channelStats.sentHelp')} />}
              </Label>
              <Value theme={theme}>{key === 'deliveryRate'
                ? (stats.delivery_rate === null ? '—' : `${(stats.delivery_rate * 100).toFixed(1)}%`)
                : formatNumber(stats[key] ?? 0)}</Value>
            </Tile>)}</Grid>
            <Card theme={theme} style={{ padding: 20, marginBottom: 20 }}>
              <SectionTitle theme={theme}>{t('channelStats.statuses')}</SectionTitle>
              {stats.by_status.filter((item) => fullAccess || !['queued', 'sent', 'failed'].includes(item.status)).map((item) => <StatusRow key={item.status} theme={theme}>
                <span>{t(`sms.statuses.${item.status}`)}</span>
                <Track theme={theme}><Fill $color={statusColor(item.status, KINDS.SMS) || theme.colors.accent}
                  $width={stats.total ? item.count / stats.total * 100 : 0} /></Track>
                <strong>{formatNumber(item.count)}</strong>
              </StatusRow>)}
            </Card>
          </>}
        <Card theme={theme} style={{ padding: 20 }}>
          <ChartHeader>
            <SectionTitle theme={theme}>{t('channelStats.trend')}<HelpTip text={t(fullAccess ? 'channelStats.trendHelp' : 'channelStats.clientTrendHelp')} /></SectionTitle>
            <Controls>
              <Select theme={theme} aria-label={t('channelStats.trend')} value={preset} onChange={(event) => setPreset(event.target.value)}>
                {[7, 14, 30, 90].map((value) => <option key={value} value={value}>{t(`dashboard.range.${value}`)}</option>)}
                <option value="custom">{t('dashboard.range.custom')}</option>
              </Select>
              {preset === 'custom' && <>
                <DateField theme={theme}>{t('dashboard.range.from')}<TextInput theme={theme} type="date" value={customFrom} max={customTo} onChange={(event) => setCustomFrom(event.target.value)} /></DateField>
                <DateField theme={theme}>{t('dashboard.range.to')}<TextInput theme={theme} type="date" value={customTo} min={customFrom} onChange={(event) => setCustomTo(event.target.value)} /></DateField>
              </>}
            </Controls>
          </ChartHeader>
          {trendError ? <EmptyStateText theme={theme}>{trendError}</EmptyStateText> : days === null ?
            <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText> : !days.some((day) => day.total) ?
              <EmptyStateText theme={theme}>{t('channelStats.empty')}</EmptyStateText> :
              <TrendChart theme={theme} data={days.map((day) => ({ ...day, success: day.delivered }))}
                totalColor={theme.colors.accent} totalLabel={t('channelStats.total')}
                completedLabel={t('channelStats.delivered')} failedLabel={t('channelStats.errors')} showFailed={fullAccess}
                formatDate={formatDate} formatDateShort={formatDate} />}
        </Card>
      </ContentScroll>
    </PageContent>
  );
};
