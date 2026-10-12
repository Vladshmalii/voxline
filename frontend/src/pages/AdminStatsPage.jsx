import { useEffect, useState, useCallback } from 'react';
import styled from 'styled-components';
import {
  FiShield,
  FiPhoneCall,
  FiCheckCircle,
  FiXCircle,
  FiClock,
  FiDollarSign,
  FiUsers,
  FiTarget,
  FiLayers,
  FiRefreshCw,
  FiPercent,
  FiActivity,
  FiMessageSquare,
} from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { adminStatsApi } from 'utils/callApi';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  Card,
  SecondaryButton,
} from 'components/ui';
import { ServicesStatusWidget } from 'components/ServicesStatusWidget';
import { HelpTip } from 'components/HelpTip';
import { toast } from 'components/Toaster';

const OrgBadge = styled.div`
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: ${({ theme }) => (theme.isDark ? '#1e1b4b' : '#ede9fe')};
  border: 1px solid ${({ theme }) => (theme.isDark ? '#4338ca' : '#c4b5fd')};
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.accent};
  margin-top: 4px;
`;

const SectionHeader = styled.h3`
  font-size: 15px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  margin: 20px 0 12px 0;
  display: flex;
  align-items: center;
  gap: 8px;
`;

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
`;

const StatCard = styled(Card)`
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
`;

const StatTop = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const StatLabel = styled.span`
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.secondary};
`;

const StatIcon = styled.div`
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: ${({ $bg }) => $bg || 'rgba(139, 92, 246, 0.12)'};
  color: ${({ $color }) => $color || '#8b5cf6'};
`;

const StatVal = styled.span`
  font-size: 22px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
  letter-spacing: -0.01em;
`;

const StatSub = styled.span`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.muted};
`;

const TariffRow = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 3px 0;

  & + & {
    border-top: 1px dashed ${({ theme }) => theme.colors.divider};
    padding-top: 7px;
  }
`;

const TariffLabel = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const TariffValue = styled.span`
  font-size: 16px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
`;

const ProgressContainer = styled.div`
  width: 100%;
  height: 8px;
  border-radius: 9999px;
  background: ${({ theme }) => theme.colors.divider};
  overflow: hidden;
  margin-top: 6px;
`;

const ProgressBar = styled.div`
  height: 100%;
  width: ${({ $pct }) => Math.min(100, Math.max(0, $pct))}%;
  background: ${({ $color }) => $color || '#8b5cf6'};
  border-radius: 9999px;
  transition: width 0.3s ease;
`;

export const AdminStatsPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminStatsApi.getStats();
      setData(res);
    } catch (err) {
      toast(err.message || t('adminStats.loadFailed'), 'error');
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const currencySymbol = data?.currency === 'RUB' ? '₽' : data?.currency === 'EUR' ? '€' : '$';

  const successPercent =
    data?.calls_total > 0 ? Math.round((data.calls_completed / data.calls_total) * 100) : 0;
  const answerRatePercent = data?.answer_rate != null ? Math.round(data.answer_rate * 100) : 0;
  const conversionPercent =
    data?.conversion_rate != null ? Math.round(data.conversion_rate * 100) : 0;

  return (
    <PageContent theme={theme}>
      <HeaderSection>
        <div>
          <PageTitle theme={theme}>{t('adminStats.title')}</PageTitle>
          {data?.organization_uuid && (
            <OrgBadge theme={theme}>
              <FiShield size={14} />
              {t('adminStats.organization', { id: data.organization_uuid })}
            </OrgBadge>
          )}
        </div>
        <HeaderActions>
          <SecondaryButton theme={theme} onClick={fetchStats} disabled={loading}>
            <FiRefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            {t('adminStats.refresh')}
          </SecondaryButton>
        </HeaderActions>
      </HeaderSection>

      <ContentScroll>
        {/* Call Funnel & Performance */}
        <SectionHeader theme={theme}>
          <FiPhoneCall size={16} />
          {t('adminStats.sections.calls')}
        </SectionHeader>

        <Grid>
          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.callsTotal.label')}
                <HelpTip text={t('adminStats.cards.callsTotal.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(139, 92, 246, 0.12)" $color="#8b5cf6">
                <FiPhoneCall size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{(data?.calls_total ?? 0).toLocaleString()}</StatVal>
            <StatSub theme={theme}>{t('adminStats.cards.callsTotal.sub')}</StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.callsSuccess.label')}
                <HelpTip text={t('adminStats.cards.callsSuccess.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(16, 185, 129, 0.12)" $color="#10b981">
                <FiCheckCircle size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{(data?.calls_completed ?? 0).toLocaleString()}</StatVal>
            <ProgressContainer theme={theme}>
              <ProgressBar $pct={successPercent} $color="#10b981" />
            </ProgressContainer>
            <StatSub theme={theme}>{t('adminStats.cards.callsSuccess.sub', { pct: successPercent })}</StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.callsFailed.label')}
                <HelpTip text={t('adminStats.cards.callsFailed.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(239, 68, 68, 0.12)" $color="#ef4444">
                <FiXCircle size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{(data?.calls_failed ?? 0).toLocaleString()}</StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.callsFailed.sub', { pct: 100 - successPercent })}
            </StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.answerRate.label')}
                <HelpTip text={t('adminStats.cards.answerRate.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(59, 130, 246, 0.12)" $color="#3b82f6">
                <FiPercent size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{answerRatePercent}%</StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.answerRate.sub', { pct: conversionPercent })}
            </StatSub>
          </StatCard>
        </Grid>

        {/* Duration & Finances */}
        <SectionHeader theme={theme}>
          <FiDollarSign size={16} />
          {t('adminStats.sections.finance')}
        </SectionHeader>

        <Grid>
          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.talkTime.label')}
                <HelpTip text={t('adminStats.cards.talkTime.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(245, 158, 11, 0.12)" $color="#f59e0b">
                <FiClock size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>
              {(data?.total_duration_minutes ?? 0).toLocaleString()} {t('adminStats.min')}
            </StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.talkTime.sub', { sec: Math.round(data?.avg_duration_seconds ?? 0) })}
            </StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('channelBilling.callBalance')}
                <HelpTip text={t('channelBilling.callsSubtitle')} />
              </StatLabel>
              <StatIcon $bg="rgba(16, 185, 129, 0.12)" $color="#10b981">
                <FiDollarSign size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>
              {currencySymbol}
              {(data?.call_balance ?? 0).toFixed(2)}
            </StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.balance.sub', { min: (data?.remaining_minutes ?? 0).toLocaleString() })}
            </StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop><StatLabel theme={theme}>{t('channelBilling.smsBalance')}</StatLabel>
              <StatIcon $bg="rgba(59, 130, 246, 0.12)" $color="#3b82f6"><FiDollarSign size={16} /></StatIcon>
            </StatTop>
            <StatVal theme={theme}>{currencySymbol}{(data?.sms_balance ?? 0).toFixed(2)}</StatVal>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.spent.label')}
                <HelpTip text={t('adminStats.cards.spent.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(239, 68, 68, 0.12)" $color="#ef4444">
                <FiActivity size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>
              {currencySymbol}
              {(data?.total_spent ?? 0).toFixed(2)}
            </StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.spent.sub', {
                amount: `${currencySymbol}${(data?.total_deposited ?? 0).toFixed(2)}`,
              })}
            </StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.tariff.label')}
                <HelpTip text={t('adminStats.cards.tariff.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(139, 92, 246, 0.12)" $color="#8b5cf6">
                <FiDollarSign size={16} />
              </StatIcon>
            </StatTop>
            <TariffRow>
              <TariffLabel theme={theme}>
                <FiPhoneCall size={13} />
                {t('adminStats.cards.tariff.call')}
              </TariffLabel>
              <TariffValue theme={theme}>
                {currencySymbol}
                {(data?.cost_per_minute ?? 0).toFixed(2)}
              </TariffValue>
            </TariffRow>
            <TariffRow theme={theme}>
              <TariffLabel theme={theme}>
                <FiMessageSquare size={13} />
                {t('adminStats.cards.tariff.sms')}
              </TariffLabel>
              <TariffValue theme={theme}>
                {currencySymbol}
                {(data?.cost_per_sms ?? 0).toFixed(2)}
              </TariffValue>
            </TariffRow>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.smsSent.label')}
                <HelpTip text={t('adminStats.cards.smsSent.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(14, 165, 233, 0.12)" $color="#0ea5e9">
                <FiMessageSquare size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{(data?.total_sms_sent ?? 0).toLocaleString()}</StatVal>
            <StatSub theme={theme}>
              {t('adminStats.cards.smsSent.sub', {
                amount: `${currencySymbol}${((data?.total_sms_sent ?? 0) * (data?.cost_per_sms ?? 0)).toFixed(2)}`,
              })}
            </StatSub>
          </StatCard>
        </Grid>

        {/* Resources Summary */}
        <SectionHeader theme={theme}>
          <FiLayers size={16} />
          {t('adminStats.sections.resources')}
        </SectionHeader>

        <Grid>
          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.agents.label')}
                <HelpTip text={t('adminStats.cards.agents.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(99, 102, 241, 0.12)" $color="#6366f1">
                <FiUsers size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{data?.agents_total ?? 0}</StatVal>
            <StatSub theme={theme}>{t('adminStats.cards.agents.sub', { count: data?.agents_active ?? 0 })}</StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.campaigns.label')}
                <HelpTip text={t('adminStats.cards.campaigns.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(236, 72, 153, 0.12)" $color="#ec4899">
                <FiTarget size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{data?.campaigns_total ?? 0}</StatVal>
            <StatSub theme={theme}>{t('adminStats.cards.campaigns.sub', { count: data?.campaigns_running ?? 0 })}</StatSub>
          </StatCard>

          <StatCard theme={theme}>
            <StatTop>
              <StatLabel theme={theme}>
                {t('adminStats.cards.leads.label')}
                <HelpTip text={t('adminStats.cards.leads.help')} />
              </StatLabel>
              <StatIcon $bg="rgba(14, 165, 233, 0.12)" $color="#0ea5e9">
                <FiUsers size={16} />
              </StatIcon>
            </StatTop>
            <StatVal theme={theme}>{(data?.leads_total ?? 0).toLocaleString()}</StatVal>
            <StatSub theme={theme}>{t('adminStats.cards.leads.sub')}</StatSub>
          </StatCard>
        </Grid>

        {/* Real-time Services Health Status */}
        <ServicesStatusWidget />
      </ContentScroll>
    </PageContent>
  );
};
