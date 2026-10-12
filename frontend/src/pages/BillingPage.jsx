import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import styled from 'styled-components';
import {
  FiDollarSign,
  FiClock,
  FiTrendingUp,
  FiPlusCircle,
  FiSliders,
  FiRefreshCw,
  FiCreditCard,
  FiCheckCircle,
} from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { billingApi } from 'utils/callApi';
import { useUser } from 'contexts/UserContext';
import { canManageBilling, canManageTariffs } from 'utils/permissions';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  Card,
  PrimaryButton,
  SecondaryButton,
  FieldGroup,
  FieldLabel,
  TextInput,
  TableContainer,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  EmptyState,
  EmptyStateTitle,
  EmptyStateText,
} from 'components/ui';
import { Pagination } from 'components/Pagination';
import { HelpTip } from 'components/HelpTip';
import { Modal } from 'components/Modal';
import { toast } from 'components/Toaster';

const SummaryGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
`;

const KpiCard = styled(Card)`
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
  overflow: hidden;
`;

const KpiIconBox = styled.div`
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: ${({ $bg }) => $bg || 'rgba(139, 92, 246, 0.12)'};
  color: ${({ $color }) => $color || '#8b5cf6'};
  margin-bottom: 4px;
`;

const KpiLabel = styled.span`
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.secondary};
`;

const KpiValue = styled.span`
  font-size: 24px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
  letter-spacing: -0.02em;
`;

const KpiSubtext = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.muted};
`;

const SectionTitle = styled.h3`
  font-size: 16px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 16px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const FilterTabs = styled.div`
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
`;

const FilterTab = styled.button`
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  border: 1px solid
    ${({ $active, theme }) => ($active ? theme.colors.accent : theme.colors.border)};
  background: ${({ $active, theme }) =>
    $active ? (theme.isDark ? '#4c1d95' : '#ede9fe') : 'transparent'};
  color: ${({ $active, theme }) =>
    $active ? theme.colors.accent : theme.colors.secondary};
  cursor: pointer;
  transition: all 0.15s ease;

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
  }
`;

const TxAmount = styled.span`
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: ${({ $positive }) => ($positive ? '#16a34a' : '#dc2626')};
`;

const QuickAmountGroup = styled.div`
  display: flex;
  gap: 8px;
  margin-top: 8px;
`;

const QuickButton = styled.button`
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.surfaceAlt || 'transparent'};
  color: ${({ theme }) => theme.colors.primary};
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    border-color: ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.accent};
  }
`;

const CalcBanner = styled.div`
  background: ${({ theme }) => (theme.isDark ? '#1e1b4b' : '#f5f3ff')};
  border: 1px solid ${({ theme }) => (theme.isDark ? '#3730a3' : '#ddd6fe')};
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 14px;
  font-size: 13px;
  color: ${({ theme }) => (theme.isDark ? '#c4b5fd' : '#5b21b6')};
  display: flex;
  align-items: center;
  gap: 8px;
`;

export const BillingPage = ({ channel = 'calls' }) => {
  const isSms = channel === 'sms';
  const { theme } = useTheme();
  const { t, locale } = useI18n();
  const user = useUser();
  const canManage = canManageBilling(user?.role);
  // Tariffs are internal (admin/super_admin); a client gets neither the editor
  // nor — in the SMS section — the rate itself (the API sends it as null).
  const canSeeTariffs = canManageTariffs(user?.role);
  const [summary, setSummary] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [txFilter, setTxFilter] = useState('all');
  const [selectedTx, setSelectedTx] = useState(null);
  const [offset, setOffset] = useState(0);
  const [transactionCount, setTransactionCount] = useState(0);
  const [loadError, setLoadError] = useState(null);
  const fetchVersion = useRef(0);

  // Modals state
  const [isTopUpOpen, setIsTopUpOpen] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState('');
  const [submittingTopUp, setSubmittingTopUp] = useState(false);

  const [isTariffOpen, setIsTariffOpen] = useState(false);
  const [tariffMin, setTariffMin] = useState('');
  const [tariffSms, setTariffSms] = useState('');
  const [tariffCurrency, setTariffCurrency] = useState('USD');
  const [submittingTariff, setSubmittingTariff] = useState(false);

  const fetchData = useCallback(async () => {
    const version = ++fetchVersion.current;
    setLoading(true);
    setLoadError(null);
    try {
      const [sumRes, txRes] = await Promise.all([
        billingApi.getSummary(),
        billingApi.listTransactions({ channel, limit: 50, offset, type: txFilter === 'deposits' ? 'deposit' : txFilter === 'charges' ? 'charges' : undefined }),
      ]);
      if (version !== fetchVersion.current) return;
      setSummary(sumRes);
      setTransactions(txRes.data || []);
      setTransactionCount(txRes.count || 0);
      if (sumRes) {
        setTariffMin(String(sumRes.cost_per_minute));
        setTariffSms(String(sumRes.cost_per_sms ?? ''));
        setTariffCurrency(sumRes.currency || 'USD');
      }
    } catch (err) {
      if (version !== fetchVersion.current) return;
      setLoadError(err.message || t('billing.toasts.loadFailed'));
    } finally {
      if (version === fetchVersion.current) setLoading(false);
    }
  }, [t, channel, offset, txFilter]);

  useEffect(() => {
    fetchData();
    return () => { fetchVersion.current += 1; };
  }, [fetchData]);

  const handleTopUpSubmit = async () => {
    const amountNum = parseFloat(topUpAmount);
    if (!Number.isFinite(amountNum) || amountNum <= 0) {
      toast(t('billing.toasts.invalidAmount'), 'error');
      return;
    }
    setSubmittingTopUp(true);
    try {
      const updated = await billingApi.topUp({ channel, amount: amountNum });
      setSummary(updated);
      setIsTopUpOpen(false);
      setTopUpAmount('');
      toast(t('billing.toasts.toppedUp', { amount: `${currencySymbol}${amountNum.toFixed(2)}` }), 'success');
      fetchData();
    } catch (err) {
      toast(err.message || t('billing.toasts.topUpFailed'), 'error');
    } finally {
      setSubmittingTopUp(false);
    }
  };

  const handleTariffSubmit = async () => {
    const costMinNum = parseFloat(tariffMin);
    const costSmsNum = parseFloat(tariffSms);
    const selectedPrice = isSms ? costSmsNum : costMinNum;
    if (!Number.isFinite(selectedPrice) || selectedPrice < 0) {
      toast(t(isSms ? 'channelBilling.invalidSmsPrice' : 'billing.toasts.invalidMinutePrice'), 'error');
      return;
    }
    setSubmittingTariff(true);
    try {
      const updated = await billingApi.updateTariffs({
        ...(isSms ? { cost_per_sms: costSmsNum } : { cost_per_minute: costMinNum }),
        currency: tariffCurrency,
      });
      setSummary(updated);
      setIsTariffOpen(false);
      toast(t('billing.toasts.tariffsUpdated'), 'success');
    } catch (err) {
      toast(err.message || t('billing.toasts.tariffsFailed'), 'error');
    } finally {
      setSubmittingTariff(false);
    }
  };

  const previewMinutes = useMemo(() => {
    const amt = parseFloat(topUpAmount);
    const cost = isSms ? summary?.cost_per_sms : summary?.cost_per_minute;
    if (isNaN(amt) || amt <= 0 || cost <= 0) return 0;
    return Math.floor(amt / cost);
  }, [topUpAmount, summary, isSms]);

  const currencySymbol = summary?.currency === 'RUB' ? '₽' : summary?.currency === 'EUR' ? '€' : '$';

  if (!summary) return <PageContent><ContentScroll><EmptyState theme={theme}>
    {loadError || t('common.loading')}
    {loadError && <SecondaryButton theme={theme} onClick={fetchData}>{t('sms.filters.refresh')}</SecondaryButton>}
  </EmptyState></ContentScroll></PageContent>;

  return (
    <PageContent theme={theme}>
      <HeaderSection>
        <div>
          <PageTitle theme={theme}>{t(isSms ? 'channelBilling.smsTitle' : 'channelBilling.callsTitle')}</PageTitle>
          <span style={{ fontSize: 13, color: theme.colors.secondary }}>
            {t(isSms ? 'channelBilling.smsSubtitle' : 'channelBilling.callsSubtitle')}
          </span>
        </div>
        <HeaderActions>
          {canSeeTariffs && (
            <SecondaryButton theme={theme} onClick={() => setIsTariffOpen(true)}>
              <FiSliders size={14} />
              {t('billing.tariffs')}
            </SecondaryButton>
          )}
          {canManage && (
            <PrimaryButton theme={theme} onClick={() => setIsTopUpOpen(true)}>
              <FiPlusCircle size={15} />
              {t('billing.topUp')}
            </PrimaryButton>
          )}
          <SecondaryButton theme={theme} onClick={fetchData} disabled={loading}>
            <FiRefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </SecondaryButton>
        </HeaderActions>
      </HeaderSection>

      <ContentScroll>
        {loadError && <EmptyStateText theme={theme}>{loadError}</EmptyStateText>}
        <SummaryGrid>
          <KpiCard theme={theme}>
            <KpiIconBox $bg="rgba(16, 185, 129, 0.12)" $color="#10b981">
              <FiDollarSign size={20} />
            </KpiIconBox>
            <KpiLabel theme={theme}>{t(isSms ? 'channelBilling.smsBalance' : 'channelBilling.callBalance')}</KpiLabel>
            <KpiValue theme={theme}>
              {currencySymbol}
              {(isSms ? summary?.sms_balance ?? 0 : summary?.call_balance ?? 0).toFixed(2)}
            </KpiValue>
            <KpiSubtext theme={theme}>
              {t('billing.kpi.totalDeposited', {
                amount: `${currencySymbol}${(isSms ? summary?.sms_deposited ?? 0 : summary?.call_deposited ?? 0).toFixed(2)}`,
              })}
            </KpiSubtext>
          </KpiCard>

          <KpiCard theme={theme}>
            <KpiIconBox $bg="rgba(139, 92, 246, 0.12)" $color="#8b5cf6">
              <FiClock size={20} />
            </KpiIconBox>
            <KpiLabel theme={theme}>{t(isSms ? 'channelBilling.remainingSms' : 'billing.kpi.remaining')}</KpiLabel>
            <KpiValue theme={theme}>
              {(isSms ? summary?.remaining_sms ?? 0 : summary?.remaining_minutes ?? 0).toLocaleString()} {t(isSms ? 'channelBilling.smsUnit' : 'billing.min')}
            </KpiValue>
            {(!isSms || canSeeTariffs) && (
              <KpiSubtext theme={theme}>
                {t(isSms ? 'channelBilling.smsTariff' : 'billing.kpi.atTariff', {
                  amount: `${currencySymbol}${(isSms ? summary?.cost_per_sms ?? 0 : summary?.cost_per_minute ?? 0).toFixed(2)}`,
                })}
              </KpiSubtext>
            )}
          </KpiCard>

          <KpiCard theme={theme}>
            <KpiIconBox $bg="rgba(239, 68, 68, 0.12)" $color="#ef4444">
              <FiTrendingUp size={20} />
            </KpiIconBox>
            <KpiLabel theme={theme}>{t('channelBilling.estimatedSpent')}<HelpTip text={t('channelBilling.estimateHelp')} /></KpiLabel>
            <KpiValue theme={theme}>
              {currencySymbol}
              {(isSms ? summary?.sms_spent ?? 0 : summary?.call_spent ?? 0).toFixed(2)}
            </KpiValue>
            <KpiSubtext theme={theme}>
              {isSms ? t('channelBilling.smsUsed', { count: (summary?.total_sms_sent ?? 0).toLocaleString() }) : t('billing.kpi.used', { minutes: (summary?.total_minutes_used ?? 0).toLocaleString() })}
            </KpiSubtext>
          </KpiCard>

          {(!isSms || canSeeTariffs) && (
          <KpiCard theme={theme}>
            <KpiIconBox $bg="rgba(59, 130, 246, 0.12)" $color="#3b82f6">
              <FiCreditCard size={20} />
            </KpiIconBox>
            <KpiLabel theme={theme}>{t('billing.kpi.rate')}</KpiLabel>
            <KpiValue theme={theme}>
              {currencySymbol}
              {(isSms ? summary?.cost_per_sms ?? 0 : summary?.cost_per_minute ?? 0).toFixed(2)}
            </KpiValue>
            <KpiSubtext theme={theme}>
              {t(isSms ? 'channelBilling.smsRate' : 'channelBilling.callTariff')}
            </KpiSubtext>
          </KpiCard>
          )}
        </SummaryGrid>

        <Card theme={theme} style={{ padding: 20 }}>
          <SectionTitle theme={theme}>
            <span>{t('billing.history.title')}</span>
          </SectionTitle>

          <FilterTabs>
            <FilterTab
              theme={theme}
              $active={txFilter === 'all'}
              onClick={() => { setTxFilter('all'); setOffset(0); }}
            >
              {t('channelBilling.all')}
            </FilterTab>
            <FilterTab
              theme={theme}
              $active={txFilter === 'deposits'}
              onClick={() => { setTxFilter('deposits'); setOffset(0); }}
            >
              {t('channelBilling.deposits')}
            </FilterTab>
            <FilterTab
              theme={theme}
              $active={txFilter === 'charges'}
              onClick={() => { setTxFilter('charges'); setOffset(0); }}
            >
              {t('channelBilling.charges')}
            </FilterTab>
          </FilterTabs>

          {loading ? <EmptyState theme={theme}>{t('common.loading')}</EmptyState> : loadError ? <EmptyState theme={theme}>{loadError}</EmptyState> : transactions.length === 0 ? (
            <EmptyState>
              <EmptyStateTitle theme={theme}>{t('billing.history.emptyTitle')}</EmptyStateTitle>
              <EmptyStateText theme={theme}>
                {t('channelBilling.empty')}
              </EmptyStateText>
            </EmptyState>
          ) : (
            <TableContainer theme={theme}>
              <Table>
                <TableHeader theme={theme}>
                  <TableRow theme={theme}>
                    <TableHeaderCell theme={theme}>{t('billing.columns.date')}</TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('billing.columns.amount')}
                    </TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('billing.columns.balanceAfter')}
                    </TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <tbody>
                {transactions.map((tx) => {
                  const isDeposit = tx.type === 'deposit' || tx.amount > 0;
                  const dateStr = new Date(tx.created_at).toLocaleString(locale);
                  return (
                    <TableRow
                      key={tx.id}
                      theme={theme}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelectedTx(tx)}
                    >
                      <TableCell theme={theme} style={{ whiteSpace: 'nowrap', fontSize: 13 }}>
                        {dateStr}
                      </TableCell>
                      <TableCell theme={theme} $align="right">
                        <TxAmount $positive={isDeposit}>
                          {isDeposit ? '+' : '-'}
                          {currencySymbol}
                          {Math.abs(tx.amount).toFixed(2)}
                        </TxAmount>
                      </TableCell>
                      <TableCell theme={theme} $align="right" style={{ color: theme.colors.secondary }}>
                        {tx.balance_after != null
                          ? `${currencySymbol}${tx.balance_after.toFixed(2)}`
                          : '—'}
                        {tx.legacy_balance_after != null && <HelpTip text={t('channelBilling.legacyBalance', { amount: `${currencySymbol}${tx.legacy_balance_after.toFixed(2)}` })} />}
                      </TableCell>
                    </TableRow>
                  );
                })}
                </tbody>
              </Table>
            </TableContainer>
          )}
          {!loadError && <Pagination offset={offset} limit={50} total={transactionCount} onChange={setOffset} disabled={loading} />}
        </Card>
      </ContentScroll>

      {/* Top Up Modal */}
      {isTopUpOpen && (
        <Modal
          title={t('billing.topUpModal.title')}
          onClose={() => setIsTopUpOpen(false)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setIsTopUpOpen(false)}>
                {t('billing.topUpModal.cancel')}
              </SecondaryButton>
              <PrimaryButton
                theme={theme}
                type="button"
                disabled={submittingTopUp}
                onClick={handleTopUpSubmit}
              >
                {submittingTopUp ? t('billing.topUpModal.submitting') : t('billing.topUpModal.submit')}
              </PrimaryButton>
            </>
          }
        >
          <FieldGroup>
            <FieldLabel theme={theme}>{t('billing.topUpModal.amount', { currency: currencySymbol })}</FieldLabel>
            <TextInput
              theme={theme}
              type="number"
              step="0.01"
              min="1"
              placeholder="100.00"
              value={topUpAmount}
              onChange={(e) => setTopUpAmount(e.target.value)}
              autoFocus
              required
            />
            <QuickAmountGroup>
              {[50, 100, 250, 500, 1000].map((amt) => (
                <QuickButton
                  key={amt}
                  type="button"
                  theme={theme}
                  onClick={() => setTopUpAmount(String(amt))}
                >
                  +{currencySymbol}
                  {amt}
                </QuickButton>
              ))}
            </QuickAmountGroup>
          </FieldGroup>

          {previewMinutes > 0 && !isSms && (
            <CalcBanner theme={theme}>
              <FiCheckCircle size={16} />
              <span
                dangerouslySetInnerHTML={{
                  __html: t('billing.topUpModal.preview', {
                    minutes: previewMinutes.toLocaleString(),
                  }),
                }}
              />
            </CalcBanner>
          )}
          {previewMinutes > 0 && isSms && <CalcBanner theme={theme}><FiCheckCircle size={16} />{t('channelBilling.smsPreview', { count: previewMinutes.toLocaleString() })}</CalcBanner>}
        </Modal>
      )}

      {/* Transaction details */}
      {selectedTx && (() => {
        const isDeposit = selectedTx.type === 'deposit' || selectedTx.amount > 0;
        const typeKey = ['deposit', 'call_usage', 'sms_usage'].includes(selectedTx.type)
          ? selectedTx.type
          : 'adjustment';
        const rows = [
          [t('billing.details.hash'), selectedTx.uuid || selectedTx.id],
          [t('billing.details.date'), new Date(selectedTx.created_at).toLocaleString()],
          [t('billing.details.type'), t(`billing.types.${typeKey}`)],
          [
            t('billing.details.amount'),
            `${isDeposit ? '+' : '-'}${currencySymbol}${Math.abs(selectedTx.amount).toFixed(2)}`,
          ],
          [
            t('billing.details.balanceAfter'),
            selectedTx.balance_after != null
              ? `${currencySymbol}${selectedTx.balance_after.toFixed(2)}`
              : '—',
          ],
          [t('billing.details.description'), selectedTx.description || '—'],
        ];
        return (
          <Modal
            title={t('billing.details.title')}
            onClose={() => setSelectedTx(null)}
            footer={
              <SecondaryButton theme={theme} type="button" onClick={() => setSelectedTx(null)}>
                {t('billing.details.close')}
              </SecondaryButton>
            }
          >
            {rows.map(([label, value]) => (
              <FieldGroup key={label} style={{ marginBottom: 12 }}>
                <FieldLabel theme={theme}>{label}</FieldLabel>
                <div style={{ fontSize: 14, color: theme.colors.primary, wordBreak: 'break-all' }}>
                  {value}
                </div>
              </FieldGroup>
            ))}
          </Modal>
        );
      })()}

      {/* Tariffs Modal */}
      {canSeeTariffs && isTariffOpen && (
        <Modal
          title={t('billing.tariffModal.title')}
          onClose={() => setIsTariffOpen(false)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setIsTariffOpen(false)}>
                {t('billing.tariffModal.cancel')}
              </SecondaryButton>
              <PrimaryButton
                theme={theme}
                type="button"
                disabled={submittingTariff}
                onClick={handleTariffSubmit}
              >
                {submittingTariff ? t('billing.tariffModal.submitting') : t('billing.tariffModal.submit')}
              </PrimaryButton>
            </>
          }
        >
          {!isSms && <FieldGroup>
            <FieldLabel theme={theme}>{t('billing.tariffModal.perMinute', { currency: currencySymbol })}</FieldLabel>
            <TextInput
              theme={theme}
              type="number"
              step="0.001"
              min="0"
              placeholder="0.10"
              value={tariffMin}
              onChange={(e) => setTariffMin(e.target.value)}
              required
            />
          </FieldGroup>}

          {isSms && <FieldGroup style={{ marginTop: 14 }}>
            <FieldLabel theme={theme}>{t('billing.tariffModal.perSms', { currency: currencySymbol })}</FieldLabel>
            <TextInput
              theme={theme}
              type="number"
              step="0.001"
              min="0"
              placeholder="0.02"
              value={tariffSms}
              onChange={(e) => setTariffSms(e.target.value)}
            />
          </FieldGroup>}

          <FieldGroup style={{ marginTop: 14 }}>
            <FieldLabel theme={theme}>{t('billing.tariffModal.currency')}</FieldLabel>
            <TextInput
              theme={theme}
              placeholder="USD"
              value={tariffCurrency}
              onChange={(e) => setTariffCurrency(e.target.value.toUpperCase())}
            />
          </FieldGroup>
        </Modal>
      )}
    </PageContent>
  );
};
