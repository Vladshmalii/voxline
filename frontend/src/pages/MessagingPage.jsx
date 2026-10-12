import { useMemo, useState } from 'react';
import { CrudPage } from 'components/CrudPage';
import { ActiveBadge } from 'components/badges';
import { formatDateTime } from 'components/ui';
import { messagingApi, MAX_PAGE } from 'utils/callApi';

// SMessagingRead — one organization's SMS route. Sibling of telephony: the
// trunk that carries audio and the route that carries text are bound
// separately, so this is its own CRUD resource rather than a field on it.
const COLUMNS = [
  { key: 'id', labelKey: 'common.id' },
  { key: 'name', labelKey: 'messaging.columns.name' },
  { key: 'adapter', labelKey: 'messaging.columns.adapter' },
  { key: 'sender', labelKey: 'messaging.columns.sender', render: (row) => row.sender ?? '—' },
  {
    key: 'is_active',
    labelKey: 'common.status',
    align: 'center',
    render: (row) => <ActiveBadge active={row.is_active} />,
  },
  { key: 'updated_at', labelKey: 'common.updatedAt', render: (row) => formatDateTime(row.updated_at) },
];

// The backend does not validate `adapter` on create — an unknown string is
// accepted silently and only fails once a message is actually sent — so it
// is offered as a closed choice here rather than free text.
const ADAPTER_OPTIONS = [
  { value: 'twilio', label: 'Twilio' },
  { value: 'mamonty', label: 'Mamonty' },
];

const MAMONTY_CHANNEL_OPTIONS = [
  { value: 'char', labelKey: 'messaging.fields.optionsFields.channelChar' },
  { value: 'digit', labelKey: 'messaging.fields.optionsFields.channelDigit' },
];

/**
 * The field set depends on the selected adapter: Twilio and Mamonty use a
 * disjoint set of credentials (account_id/sender_pool_id are Mamonty-unused;
 * Mamonty's auth_token is an "API key", not Twilio's "Auth Token") and only
 * Mamonty exposes an `options.channel` choice. `channel` is passed in
 * separately since `sender`'s "required" only applies once "char" is chosen.
 */
const buildFields = (adapter, channel) => [
  { name: 'name', labelKey: 'messaging.fields.name', type: 'text', required: true },
  {
    name: 'adapter',
    labelKey: 'messaging.fields.adapter',
    type: 'select',
    required: true,
    default: 'twilio',
    options: ADAPTER_OPTIONS,
    hintKey: 'messaging.fields.adapterHint',
  },
  { name: 'is_active', labelKey: 'messaging.fields.isActive', type: 'checkbox', default: false },
  {
    name: 'account_id',
    labelKey: 'messaging.fields.accountId',
    type: 'text',
    nullable: true,
    required: adapter === 'twilio',
    showIf: (values) => values.adapter !== 'mamonty',
  },
  {
    name: 'auth_token',
    labelKey: adapter === 'mamonty' ? 'messaging.fields.authTokenMamonty' : 'messaging.fields.authToken',
    type: 'password',
    nullable: true,
    required: true,
    hintKey: adapter === 'mamonty' ? 'messaging.fields.authTokenMamontyHint' : undefined,
  },
  {
    name: 'sender',
    labelKey: adapter === 'mamonty' ? 'messaging.fields.senderMamonty' : 'messaging.fields.sender',
    type: 'text',
    nullable: true,
    required: adapter === 'mamonty' && channel === 'char',
    hintKey: adapter === 'mamonty' ? 'messaging.fields.senderMamontyHint' : 'messaging.fields.senderHint',
  },
  {
    name: 'sender_pool_id',
    labelKey: 'messaging.fields.senderPoolId',
    type: 'text',
    nullable: true,
    showIf: (values) => values.adapter !== 'mamonty',
    hintKey: 'messaging.fields.senderPoolIdHint',
  },
  {
    name: 'control_url',
    labelKey: 'messaging.fields.controlUrl',
    type: 'text',
    nullable: true,
    hintKey: adapter === 'mamonty' ? 'messaging.fields.controlUrlMamontyHint' : undefined,
  },
  {
    name: 'capabilities',
    labelKey: 'messaging.fields.capabilities',
    type: 'json',
    default: {},
    rows: 3,
    hintKey: 'messaging.fields.capabilitiesHint',
  },
  {
    name: 'options',
    labelKey: 'messaging.fields.options',
    type: 'object',
    nullable: true,
    fields: [
      {
        name: 'region',
        labelKey: 'messaging.fields.optionsFields.region',
        type: 'text',
        nullable: true,
        showIf: (values) => values.adapter !== 'mamonty',
        hintKey: 'messaging.fields.optionsFields.regionHint',
      },
      {
        name: 'edge',
        labelKey: 'messaging.fields.optionsFields.edge',
        type: 'text',
        nullable: true,
        showIf: (values) => values.adapter !== 'mamonty',
        hintKey: 'messaging.fields.optionsFields.edgeHint',
      },
      {
        name: 'channel',
        labelKey: 'messaging.fields.optionsFields.channel',
        type: 'select',
        nullable: true,
        showIf: (values) => values.adapter === 'mamonty',
        emptyLabelKey: 'messaging.fields.optionsFields.channelAuto',
        options: MAMONTY_CHANNEL_OPTIONS,
        hintKey: 'messaging.fields.optionsFields.channelHint',
      },
      {
        name: 'timeout',
        labelKey: 'messaging.fields.optionsFields.timeout',
        type: 'number',
        nullable: true,
        hintKey: 'messaging.fields.optionsFields.timeoutHint',
      },
      {
        name: 'status_url_base',
        labelKey: 'messaging.fields.optionsFields.statusUrlBase',
        type: 'text',
        nullable: true,
        hintKey: 'messaging.fields.optionsFields.statusUrlBaseHint',
      },
    ],
  },
];

export const MessagingPage = () => {
  const api = useMemo(() => ({ ...messagingApi, list: () => messagingApi.list({ limit: MAX_PAGE }) }), []);

  // The field set (labels, required, visibility) depends on the adapter and,
  // for Mamonty, the chosen channel — CrudPage's onFormValues reports the
  // form's live values so the fields can be rebuilt to match.
  const [adapter, setAdapter] = useState('twilio');
  const [channel, setChannel] = useState('');

  const handleFormValues = (values) => {
    setAdapter(values?.adapter || 'twilio');
    setChannel(values?.['options.channel'] || '');
  };

  const fields = useMemo(() => buildFields(adapter, channel), [adapter, channel]);

  return (
    <CrudPage
      titleKey="messaging.title"
      api={api}
      columns={COLUMNS}
      fields={fields}
      rowClickEdit
      onFormValues={handleFormValues}
      emptyTextKey="messaging.empty"
    />
  );
};
