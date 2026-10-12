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
  border-radius: ${({ theme }) => theme.radii.pill};
  background: ${({ $status, theme }) => {
    if ($status === 'operational') return theme.mode === 'dark' ? '#0F2E1D' : '#DCFCE7';
    if ($status === 'degraded') return theme.mode === 'dark' ? '#3A2A0A' : '#FEF3C7';
    return theme.mode === 'dark' ? '#3B1414' : '#FEE2E2';
  }};
  color: ${({ $status, theme }) => {
    if ($status === 'operational') return theme.mode === 'dark' ? '#86EFAC' : '#166534';
    if ($status === 'degraded') return theme.mode === 'dark' ? '#FDE68A' : '#92400E';
    return theme.mode === 'dark' ? '#FCA5A5' : '#991B1B';
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
    ${({ $isDown, theme }) => ($isDown ? '#DC2626' : theme.colors.border)};
  border-radius: ${({ theme }) => theme.radii.sm};
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.15s ease;

  ${({ $isDown }) =>
    $isDown &&
    `
    background: rgba(220, 38, 38, 0.06);
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
    if ($status === 'operational') return '#16A34A';
    if ($status === 'degraded') return '#D97706';
    return '#DC2626';
  }};
  box-shadow: 0 0 8px ${({ $status }) => ($status === 'operational' ? '#16A34A88' : '#DC262688')};
`;

const ServiceMsg = styled.p`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0;
  line-height: 1.4;
`;

const LatencyText = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.muted};
  font-family: monospace;
`;

const AlertBanner = styled.div`
  background: ${({ theme }) => (theme.mode === 'dark' ? '#2A0F0F' : '#FEF2F2')};
  border: 1px solid #DC2626;
  border-radius: ${({ theme }) => theme.radii.sm};
  padding: 10px 14px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: ${({ theme }) => (theme.mode === 'dark' ? '#FCA5A5' : '#991B1B')};
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
          <FiAlertTriangle size={18} color="#DC2626" />
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
