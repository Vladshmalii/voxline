import { useState } from 'react';
import styled from 'styled-components';
import { Modal } from 'components/Modal';
import { Pagination } from 'components/Pagination';
import { StatusBadge } from 'components/badges';
import { KINDS } from 'utils/statusMap';
import {
  TableContainer,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  EmptyStateText,
  formatDateTime,
} from 'components/ui';
import { callsApi, MAX_PAGE } from 'utils/callApi';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

const HistoryTable = styled(Table)`
  margin-bottom: 16px;
`;

const ClientGrid = styled.div`
  display: grid;
  grid-template-columns: minmax(100px, max-content) 1fr minmax(100px, max-content) 1fr;
  gap: 8px 16px;
  align-items: baseline;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const ClientKey = styled.div`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
`;

const ClientValue = styled.div`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  word-break: break-word;
`;

// The lead row this modal is opened from (AudiencesPage's Leads table) already
// carries the client's full profile, not just id/phone/name — showing it here
// too means this modal answers "who is this and what have we done with them"
// in one place, rather than the call table alone (which only answers the
// second half). Every field is optional: a caller could still pass a bare
// {id, phone, name} stub, so anything missing on `client` just doesn't render.
const ClientCard = ({ client, theme, t, onEdit }) => (
  <div style={{ marginBottom: 18, paddingBottom: 14, borderBottom: `1px solid ${theme.colors.border}` }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: theme.colors.primary }}>
        {client.name || client.phone || `#${client.id}`}
      </div>
      {onEdit && (
        <button
          type="button"
          onClick={() => onEdit(client)}
          style={{
            background: 'none',
            border: `1px solid ${theme.colors.border}`,
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 12,
            fontWeight: 600,
            color: theme.colors.primary,
            cursor: 'pointer',
          }}
        >
          {t('audiences.leads.edit')}
        </button>
      )}
    </div>
    <ClientGrid theme={theme}>
      <ClientKey theme={theme}>{t('audiences.leads.columns.phone')}</ClientKey>
      <ClientValue theme={theme}>{client.phone || '—'}</ClientValue>

      <ClientKey theme={theme}>{t('audiences.leads.columns.status')}</ClientKey>
      <ClientValue theme={theme}>
        <StatusBadge kind={KINDS.CLIENT} value={client.status} />
      </ClientValue>

      <ClientKey theme={theme}>{t('audiences.leads.columns.country')}</ClientKey>
      <ClientValue theme={theme}>{client.country || '—'}</ClientValue>

      <ClientKey theme={theme}>{t('audiences.leads.columns.language')}</ClientKey>
      <ClientValue theme={theme}>{client.language || '—'}</ClientValue>

      <ClientKey theme={theme}>{t('audiences.leads.columns.answeredCalls')}</ClientKey>
      <ClientValue theme={theme}>{client.answered_calls ?? 0}</ClientValue>

      <ClientKey theme={theme}>{t('audiences.leads.columns.lastActive')}</ClientKey>
      <ClientValue theme={theme}>
        {client.last_active ? formatDateTime(client.last_active) : '—'}
      </ClientValue>

      {Array.isArray(client.audiences) && client.audiences.length > 0 && (
        <>
          <ClientKey theme={theme}>{t('audiences.leads.columns.audience')}</ClientKey>
          <ClientValue theme={theme} style={{ gridColumn: 'span 3' }}>
            {client.audiences.join(', ')}
          </ClientValue>
        </>
      )}
    </ClientGrid>
  </div>
);

/**
 * One client's profile plus their call history across every campaign — "who
 * is this, and has this number actually been dialed, how many times, with
 * what outcome" without hunting through the Calls page's flat list for one
 * phone number among otherwise identical-looking rows or scrolling the Leads
 * table sideways for their segment/VIP/deposit fields. `ClientCard` above
 * renders whatever profile fields `client` carries; the summary line and
 * table below cover the calls.
 *
 * The headline number is *dial attempts*, not "call records": re-uploading
 * a contact after its previous Call already went terminal creates a new
 * Call row (each usually with just one CallAttempt of its own) — so five
 * real dial attempts to one number can show up as five separate Call rows
 * of one attempt each, not one Call with five attempts the way a retry
 * would. Counting Call rows alone reads as "we only tried once, five
 * times" — summing `attempts_made` across every Call for this client is
 * the number an operator actually means by "how many times did we call
 * them."
 *
 * Usage: `const history = useClientCallHistory();` then
 * `history.open(client)` (any object with `.id` and `.phone`/`.name`) and
 * render `<ClientCallHistoryModal {...history} campaignById={campaignById} />`
 * — `campaignById` is optional, a `Map<id, {name}>` for resolving
 * `campaign_id` to a name; omitted, rows just show `#id`.
 */
export const useClientCallHistory = () => {
  const [callHistory, setCallHistory] = useState(null); // { client, rows, total, error, offset, pageSize, summary }

  // Paginated (a number can rack up dozens/hundreds of calls over time) —
  // rows/total reflect just the current page. The completed/canceled/
  // no-answer counts in the summary line are NOT derived from `rows` (that
  // would silently only describe the current page): three tiny `limit=1`
  // count-only requests, same "read .count, ignore the page" trick used
  // everywhere else in this app that has no dedicated aggregate endpoint.
  const loadPage = (client, offset, pageSize) => {
    setCallHistory((prev) =>
      prev && prev.client.id === client.id ? { ...prev, rows: null, offset, pageSize } : prev
    );
    callsApi
      .list({ client_id: client.id, limit: pageSize, offset })
      .then((res) => {
        setCallHistory((prev) =>
          prev && prev.client.id === client.id
            ? { ...prev, rows: Array.isArray(res?.data) ? res.data : [], total: res?.count ?? 0 }
            : prev
        );
      })
      .catch((e) => {
        setCallHistory((prev) =>
          prev && prev.client.id === client.id ? { ...prev, rows: [], error: e.message } : prev
        );
      });
  };

  const open = (client) => {
    if (!client?.id) return;
    setCallHistory({
      client,
      rows: null,
      total: 0,
      error: null,
      offset: 0,
      pageSize: DEFAULT_PAGE_SIZE,
      summary: null,
    });
    Promise.all([
      callsApi.list({ client_id: client.id, status: 'completed', limit: 1 }),
      callsApi.list({ client_id: client.id, status: 'canceled', limit: 1 }),
      callsApi.list({ client_id: client.id, outcome: 'no_answer', limit: 1 }),
      // Every Call row for this client, just to sum attempts_made — see the
      // module docstring for why that sum (not the Call-row count) is the
      // number that answers "how many times did we actually dial them."
      // Capped at MAX_PAGE like every other unpaginated lookup in this app;
      // one number racking up more calls than that is not a case this
      // summary line needs to get exactly right.
      callsApi.list({ client_id: client.id, limit: MAX_PAGE }),
    ])
      .then(([completed, canceled, noAnswer, all]) => {
        const totalAttempts = Array.isArray(all?.data)
          ? all.data.reduce((sum, call) => sum + (call.attempts_made || 0), 0)
          : null;
        setCallHistory((prev) =>
          prev && prev.client.id === client.id
            ? {
                ...prev,
                summary: {
                  completed: completed?.count ?? 0,
                  canceled: canceled?.count ?? 0,
                  noAnswer: noAnswer?.count ?? 0,
                  totalAttempts,
                },
              }
            : prev
        );
      })
      .catch(() => undefined); // a summary line is a nice-to-have; the page below is what matters
    loadPage(client, 0, DEFAULT_PAGE_SIZE);
  };

  const close = () => setCallHistory(null);
  const changeOffset = (offset) => loadPage(callHistory.client, offset, callHistory.pageSize);
  const changePageSize = (pageSize) => loadPage(callHistory.client, 0, pageSize);

  return { callHistory, open, close, changeOffset, changePageSize };
};

export const ClientCallHistoryModal = ({
  callHistory,
  close,
  changeOffset,
  changePageSize,
  campaignById,
  theme,
  t,
  onEdit,
}) => {
  if (!callHistory) return null;

  return (
    <Modal
      title={t('audiences.callHistory.title', {
        phone: callHistory.client.phone || callHistory.client.name || `#${callHistory.client.id}`,
      })}
      onClose={close}
      wide
    >
      <ClientCard client={callHistory.client} theme={theme} t={t} onEdit={onEdit} />
      {callHistory.error ? (
        <EmptyStateText theme={theme}>{callHistory.error}</EmptyStateText>
      ) : callHistory.rows === null ? (
        <EmptyStateText theme={theme}>{t('common.loading')}</EmptyStateText>
      ) : callHistory.rows.length === 0 ? (
        <EmptyStateText theme={theme}>{t('audiences.callHistory.noCalls')}</EmptyStateText>
      ) : (
        <>
          <EmptyStateText theme={theme} style={{ marginBottom: 10 }}>
            {t('audiences.callHistory.summary', {
              total: callHistory.total,
              totalAttempts: callHistory.summary?.totalAttempts ?? '…',
              completed: callHistory.summary?.completed ?? '…',
              canceled: callHistory.summary?.canceled ?? '…',
              noAnswer: callHistory.summary?.noAnswer ?? '…',
            })}
          </EmptyStateText>
          <TableContainer theme={theme}>
            <HistoryTable>
              <TableHeader theme={theme}>
                <tr>
                  <TableHeaderCell theme={theme}>{t('common.id')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('audiences.callHistory.columns.when')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('common.status')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('audiences.callHistory.columns.outcome')}</TableHeaderCell>
                  <TableHeaderCell theme={theme}>{t('audiences.callHistory.columns.campaign')}</TableHeaderCell>
                  <TableHeaderCell theme={theme} $align="right">
                    {t('audiences.callHistory.columns.attempts')}
                  </TableHeaderCell>
                  <TableHeaderCell theme={theme} $align="right">
                    {t('audiences.callHistory.columns.duration')}
                  </TableHeaderCell>
                </tr>
              </TableHeader>
              <tbody>
                {callHistory.rows.map((call) => (
                  <TableRow key={call.id} theme={theme}>
                    <TableCell theme={theme}>{call.id}</TableCell>
                    <TableCell theme={theme}>{formatDateTime(call.created_at)}</TableCell>
                    <TableCell theme={theme}>
                      <StatusBadge kind={KINDS.CALL} value={call.status} />
                    </TableCell>
                    <TableCell theme={theme}>
                      {call.outcome ? <StatusBadge kind={KINDS.OUTCOME} value={call.outcome} /> : '—'}
                    </TableCell>
                    <TableCell theme={theme}>
                      {call.campaign_id != null
                        ? campaignById?.get(call.campaign_id)?.name || `#${call.campaign_id}`
                        : '—'}
                    </TableCell>
                    <TableCell theme={theme} $align="right">{call.attempts_made}</TableCell>
                    <TableCell theme={theme} $align="right">{call.duration_seconds ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </tbody>
            </HistoryTable>
          </TableContainer>
          <Pagination
            offset={callHistory.offset}
            limit={callHistory.pageSize}
            total={callHistory.total}
            onChange={changeOffset}
            pageSize={callHistory.pageSize}
            onPageSizeChange={changePageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
          />
        </>
      )}
    </Modal>
  );
};
