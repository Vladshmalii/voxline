import { useCallback, useEffect, useState } from 'react';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { Modal } from 'components/Modal';
import { RefreshButton } from 'components/RefreshButton';
import { toast } from 'components/Toaster';
import { agentsApi, MAX_PAGE } from 'utils/callApi';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  SecondaryButton,
  DangerButton,
  TableContainer,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  RowActions,
  RowActionButton,
  EmptyState,
  EmptyStateTitle,
  EmptyStateText,
} from 'components/ui';

// VOAD-62: owner/admin/super_admin review staff-authored SMS-tool text
// before it can ever be sent (the engine refuses to even offer the tool to
// the model while pending — see the backend's build_context). A
// custom page rather than CrudPage: approve/reject aren't create/edit/
// delete, and reject needs a real confirmation step CrudPage's rowActions
// don't actually implement.
export const SmsModerationPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();

  const [rows, setRows] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rejecting, setRejecting] = useState(null); // row pending reject confirm

  const reload = useCallback(() => {
    setLoadError(null);
    setLoading(true);
    agentsApi
      .list({ sms_status: 'pending', limit: MAX_PAGE })
      .then((data) => setRows(Array.isArray(data) ? data : []))
      .catch((e) => {
        setLoadError(e.message);
        setRows([]);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const approve = async (row) => {
    setBusyId(row.id);
    try {
      await agentsApi.approveSms(row.id);
      toast(t('agents.smsModeration.approved'), 'success');
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusyId(null);
    }
  };

  const confirmReject = async () => {
    const row = rejecting;
    setBusyId(row.id);
    try {
      await agentsApi.rejectSms(row.id);
      toast(t('agents.smsModeration.rejected'), 'success');
      setRejecting(null);
      reload();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <PageTitle theme={theme}>{t('agents.smsModeration.title')}</PageTitle>
        <HeaderActions>
          <RefreshButton onClick={reload} loading={loading} />
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        {rows === null ? (
          <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
        ) : loadError ? (
          <EmptyState theme={theme}>
            <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
            <EmptyStateText theme={theme}>{loadError}</EmptyStateText>
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState theme={theme}>
            <EmptyStateText theme={theme}>{t('agents.smsModeration.empty')}</EmptyStateText>
          </EmptyState>
        ) : (
          <TableContainer theme={theme}>
            <Table>
              <TableHeader theme={theme}>
                <tr>
                  <TableHeaderCell theme={theme}>{t('common.id')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('agents.smsModeration.columns.agent')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('agents.smsModeration.columns.message')}</TableHeaderCell>
                  <TableHeaderCell theme={theme} $align="right">
                    {t('common.actions')}
                  </TableHeaderCell>
                </tr>
              </TableHeader>
              <tbody>
                {rows.map((row) => (
                  <TableRow key={row.id} theme={theme}>
                    <TableCell theme={theme}>{row.id}</TableCell>
                    <TableCell theme={theme}>{row.name}</TableCell>
                    <TableCell theme={theme}>{row.sms_tool_message}</TableCell>
                    <TableCell theme={theme} $align="right">
                      <RowActions style={{ justifyContent: 'flex-end' }}>
                        <RowActionButton
                          theme={theme}
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => approve(row)}
                        >
                          {t('agents.smsModeration.approve')}
                        </RowActionButton>
                        <RowActionButton
                          theme={theme}
                          type="button"
                          $danger
                          disabled={busyId === row.id}
                          onClick={() => setRejecting(row)}
                        >
                          {t('agents.smsModeration.reject')}
                        </RowActionButton>
                      </RowActions>
                    </TableCell>
                  </TableRow>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </ContentScroll>

      {rejecting && (
        <Modal
          title={`${t('agents.smsModeration.reject')} — ${rejecting.name}`}
          onClose={() => setRejecting(null)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setRejecting(null)}>
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton theme={theme} type="button" disabled={busyId === rejecting.id} onClick={confirmReject}>
                {t('agents.smsModeration.reject')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>{t('agents.smsModeration.confirmReject')}</EmptyStateText>
        </Modal>
      )}
    </PageContent>
  );
};
