import { useMemo } from 'react';
import { CrudPage } from 'components/CrudPage';
import { formatDateTime } from 'components/ui';
import { providersApi, MAX_PAGE } from 'utils/callApi';

// SModelProviderRead. The api_key column only says whether one is set — the
// value itself stays in the edit form.
const COLUMNS = [
  { key: 'id', labelKey: 'common.id' },
  { key: 'name', labelKey: 'providers.columns.name' },
  { key: 'url', labelKey: 'providers.columns.url' },
  {
    key: 'api_key',
    labelKey: 'providers.columns.apiKey',
    align: 'center',
    render: (row) => (row.has_api_key ? '•••' : '—'),
  },
  { key: 'updated_at', labelKey: 'common.updatedAt', render: (row) => formatDateTime(row.updated_at) },
];

const FIELDS = [
  { name: 'name', labelKey: 'providers.fields.name', type: 'text', required: true },
  { name: 'url', labelKey: 'providers.fields.url', type: 'text', required: true, placeholder: 'https://…' },
  {
    name: 'api_key',
    labelKey: 'providers.fields.apiKey',
    type: 'password',
    nullable: true,
    hintKey: 'providers.fields.apiKeyHint',
  },
  {
    name: 'options',
    labelKey: 'providers.fields.options',
    type: 'json',
    default: {},
    rows: 3,
    hintKey: 'providers.fields.optionsHint',
  },
];

export const ProvidersPage = () => {
  const api = useMemo(() => ({ ...providersApi, list: () => providersApi.list({ limit: MAX_PAGE }) }), []);

  return (
    <CrudPage
      titleKey="providers.title"
      api={api}
      columns={COLUMNS}
      fields={FIELDS}
      rowClickEdit
      emptyTextKey="providers.empty"
    />
  );
};
