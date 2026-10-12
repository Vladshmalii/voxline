import { useEffect, useState, useCallback } from 'react';
import styled from 'styled-components';
import {
  FiCheckCircle,
  FiAlertTriangle,
  FiXCircle,
  FiPhone,
  FiCpu,
  FiMessageSquare,
  FiDatabase,
  FiRefreshCw,
} from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { servicesApi } from 'utils/callApi';
import { Card, SecondaryButton } from './ui';

const Header = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
`;

const Title = styled.h3`
  font-size: 15px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
`;

const OverallBadge = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 9999px;
  background: ${({ $status, theme }) => {
    if ($status === 'operational') return theme.isDark ? '#064e3b' : '#dcfce7';
    if ($status === 'degraded') return theme.isDark ? '#78350f' : '#fef3c7';
    return theme.isDark ? '#7f1d1d' : '#fee2e2';
  }};
  color: ${({ $status, theme }) => {
    if ($status === 'operational') return theme.isDark ? '#6ee7b7' : '#166534';
    if ($status === 'degraded') return theme.isDark ? '#fde68a' : '#92400e';
    return theme.isDark ? '#fca5a5' : '#991b1b';
  }};
`;

const Grid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
`;

const ServiceCard = styled.div`
  background: ${({ theme }) => theme.colors.surfaceAlt || theme.colors.background};
  border: 1px solid
    ${({ $isDown, theme }) => ($isDown ? '#ef4444' : theme.colors.border)};
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.15s ease;

  ${({ $isDown }) =>
    $isDown &&
    `
    background: rgba(239, 68, 68, 0.06);
  `}
`;

const ServiceTop = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const ServiceName = styled.span`
  font-size: 13px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  display: flex;
  align-items: center;
  gap: 6px;
`;

const StatusDot = styled.span`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${({ $status }) => {
    if ($status === 'operational') return '#22c55e';
    if ($status === 'degraded') return '#f59e0b';
    return '#ef4444';
  }};
  box-shadow: 0 0 8px ${({ $status }) => ($status === 'operational' ? '#22c55e88' : '#ef444488')};
`;

const ServiceMsg = styled.p`
  font-size: 11px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0;
  line-height: 1.4;
`;

const LatencyText = styled.span`
  font-size: 10px;
  color: ${({ theme }) => theme.colors.muted};
  font-family: monospace;
`;

const AlertBanner = styled.div`
  background: ${({ theme }) => (theme.isDark ? '#450a0a' : '#fef2f2')};
  border: 1px solid #ef4444;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: ${({ theme }) => (theme.isDark ? '#fca5a5' : '#991b1b')};
  font-size: 13px;
  font-weight: 500;
`;

const getCategoryIcon = (category) => {
  switch (category) {
    case 'telephony':
      return <FiPhone size={14} />;
    case 'stt':
    case 'tts':
    case 'ttt':
      return <FiCpu size={14} />;
    case 'messaging':
      return <FiMessageSquare size={14} />;
    case 'database':
      return <FiDatabase size={14} />;
    default:
      return <FiCheckCircle size={14} />;
  }
};

export const ServicesStatusWidget = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await servicesApi.getStatus();
      setData(res);
    } catch {
      // Ignore background errors
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (!data) return null;

  const isTelephonyDown = !data.telephony_operational;

  return (
    <Card theme={theme} style={{ marginTop: 20, marginBottom: 20 }}>
      {isTelephonyDown && (
        <AlertBanner theme={theme}>
          <FiAlertTriangle size={18} color="#ef4444" />
          <span>{t('dashboard.services.telephonyDown')}</span>
        </AlertBanner>
      )}

      <Header>
        <Title theme={theme}>
          <span>{t('dashboard.services.title')}</span>
          <OverallBadge theme={theme} $status={data.status}>
            {data.status === 'operational' ? (
              <>
                <FiCheckCircle size={13} /> {t('dashboard.services.operational')}
              </>
            ) : data.status === 'degraded' ? (
              <>
                <FiAlertTriangle size={13} /> {t('dashboard.services.degraded')}
              </>
            ) : (
              <>
                <FiXCircle size={13} /> {t('dashboard.services.down')}
              </>
            )}
          </OverallBadge>
        </Title>
        <SecondaryButton
          theme={theme}
          onClick={fetchStatus}
          disabled={loading}
          style={{ padding: '4px 8px', fontSize: 12 }}
        >
          <FiRefreshCw size={12} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          {t('dashboard.services.refresh')}
        </SecondaryButton>
      </Header>

      <Grid>
        {data.services?.map((srv) => (
          <ServiceCard
            key={srv.name}
            theme={theme}
            $isDown={srv.status === 'down' || (srv.category === 'telephony' && srv.status !== 'operational')}
          >
            <ServiceTop>
              <ServiceName theme={theme}>
                {getCategoryIcon(srv.category)}
                {srv.name}
              </ServiceName>
              <StatusDot $status={srv.status} />
            </ServiceTop>
            <ServiceMsg theme={theme}>{srv.message}</ServiceMsg>
            {srv.latency_ms != null && (
              <LatencyText theme={theme}>{t('dashboard.services.latency', { ms: srv.latency_ms })}</LatencyText>
            )}
          </ServiceCard>
        ))}
      </Grid>
    </Card>
  );
};
