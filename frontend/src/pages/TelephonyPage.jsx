import { useMemo } from 'react';
import { CrudPage } from 'components/CrudPage';
import { ActiveBadge } from 'components/badges';
import { formatDateTime } from 'components/ui';
import { telephonyApi, MAX_PAGE } from 'utils/callApi';

// STelephonyRead — carrier/bridge bindings agents dial out through.
const COLUMNS = [
  { key: 'id', labelKey: 'common.id' },
  { key: 'name', labelKey: 'telephony.columns.name' },
  { key: 'adapter', labelKey: 'telephony.columns.adapter' },
  { key: 'caller_id', labelKey: 'telephony.columns.callerId', render: (row) => row.caller_id ?? '—' },
  {
    key: 'is_active',
    labelKey: 'common.status',
    align: 'center',
    render: (row) => <ActiveBadge active={row.is_active} />,
  },
  { key: 'updated_at', labelKey: 'common.updatedAt', render: (row) => formatDateTime(row.updated_at) },
];

const FIELDS = [
  { name: 'name', labelKey: 'telephony.fields.name', type: 'text', required: true },
  {
    name: 'adapter',
    labelKey: 'telephony.fields.adapter',
    type: 'text',
    required: true,
    hintKey: 'telephony.fields.adapterHint',
  },
  { name: 'is_active', labelKey: 'telephony.fields.isActive', type: 'checkbox', default: false },
  { name: 'account_id', labelKey: 'telephony.fields.accountId', type: 'text', nullable: true },
  { name: 'auth_token', labelKey: 'telephony.fields.authToken', type: 'password', nullable: true },
  {
    name: 'caller_id',
    labelKey: 'telephony.fields.callerId',
    type: 'text',
    nullable: true,
    hintKey: 'telephony.fields.callerIdHint',
  },
  { name: 'control_url', labelKey: 'telephony.fields.controlUrl', type: 'text', nullable: true },
  {
    name: 'capabilities',
    labelKey: 'telephony.fields.capabilities',
    type: 'json',
    default: {},
    rows: 3,
    hintKey: 'telephony.fields.capabilitiesHint',
  },
  {
    name: 'options',
    labelKey: 'telephony.fields.options',
    type: 'json',
    default: {},
    rows: 3,
    hintKey: 'telephony.fields.optionsHint',
  },
];

export const TelephonyPage = () => {
  const api = useMemo(() => ({ ...telephonyApi, list: () => telephonyApi.list({ limit: MAX_PAGE }) }), []);

  return (
    <CrudPage
      titleKey="telephony.title"
      api={api}
      columns={COLUMNS}
      fields={FIELDS}
      rowClickEdit
      emptyTextKey="telephony.empty"
    />
  );
};
