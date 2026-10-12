import { useState, useEffect, useMemo } from 'react';
import { CrudPage } from 'components/CrudPage';
import { ActiveBadge } from 'components/badges';
import { Badge, formatDateTime } from 'components/ui';
import { modelsApi, providersApi, MAX_PAGE } from 'utils/callApi';
import { useUser } from 'contexts/UserContext';
import { canManageModels } from 'utils/permissions';

const KIND_COLORS = { stt: '#2563eb', tts: '#16a34a', ttt: '#7c3aed' };

// SttAdapterEnum + TtsAdapterEnum + TttAdapterEnum, tagged with the kind each
// serves so one flat select stays honest.
const ADAPTERS = [
  { value: 'qwen3_asr', label: 'qwen3_asr (stt)' },
  { value: 'voxtral', label: 'voxtral (stt)' },
  { value: 'cartesia', label: 'cartesia (stt/tts)' },
  { value: 'deepgram', label: 'deepgram (stt/tts)' },
  { value: 'openrouter', label: 'openrouter (stt/tts)' },
  { value: 'qwen3_tts', label: 'qwen3_tts (tts)' },
  { value: 'openai_compatible', label: 'openai_compatible (ttt)' },
];

export const ModelsPage = () => {
  const user = useUser();
  const readOnly = !canManageModels(user?.role);
  const [providers, setProviders] = useState([]);

  useEffect(() => {
    providersApi
      .list({ limit: MAX_PAGE })
      .then((data) => setProviders(Array.isArray(data) ? data : []))
      .catch(() => undefined);
  }, []);

  const providerById = useMemo(() => new Map(providers.map((p) => [p.id, p])), [providers]);

  const columns = useMemo(
    () => [
      { key: 'id', labelKey: 'common.id' },
      { key: 'name', labelKey: 'models.columns.name' },
      {
        key: 'kind',
        labelKey: 'models.columns.kind',
        align: 'center',
        render: (row) => <Badge $color={KIND_COLORS[row.kind] || '#6b7280'}>{row.kind}</Badge>,
      },
      { key: 'adapter', labelKey: 'models.columns.adapter' },
      { key: 'code', labelKey: 'models.columns.code' },
      {
        key: 'provider_id',
        labelKey: 'models.columns.provider',
        render: (row) => providerById.get(row.provider_id)?.name ?? `#${row.provider_id}`,
      },
      {
        key: 'is_active',
        labelKey: 'common.status',
        align: 'center',
        render: (row) => <ActiveBadge active={row.is_active} />,
      },
      { key: 'is_default', labelKey: 'models.fields.isDefault', render: (row) => <ActiveBadge active={row.is_default} /> },
      { key: 'updated_at', labelKey: 'common.updatedAt', render: (row) => formatDateTime(row.updated_at) },
    ],
    [providerById]
  );

  const fields = useMemo(
    () => [
      { name: 'name', labelKey: 'models.fields.name', type: 'text', required: true },
      {
        // SModelUpdate has no `kind`: which side of the pipeline a model serves
        // is fixed at creation.
        name: 'kind',
        labelKey: 'models.fields.kind',
        type: 'select',
        required: true,
        createOnly: true,
        hintKey: 'models.fields.kindHint',
        options: [
          { value: 'stt', labelKey: 'models.kinds.stt' },
          { value: 'tts', labelKey: 'models.kinds.tts' },
          { value: 'ttt', labelKey: 'models.kinds.ttt' },
        ],
      },
      {
        name: 'adapter',
        labelKey: 'models.fields.adapter',
        type: 'select',
        required: true,
        hintKey: 'models.fields.adapterHint',
        options: ADAPTERS,
      },
      {
        name: 'code',
        labelKey: 'models.fields.code',
        type: 'text',
        required: true,
        hintKey: 'models.fields.codeHint',
      },
      {
        name: 'provider_id',
        labelKey: 'models.fields.provider',
        type: 'select',
        asNumber: true,
        required: true,
        options: providers.map((p) => ({ value: p.id, label: `${p.name} (${p.url})` })),
      },
      { name: 'is_active', labelKey: 'models.fields.isActive', type: 'checkbox', default: false },
      { name: 'is_default', labelKey: 'models.fields.isDefault', type: 'checkbox', default: false, hintKey: 'models.fields.isDefaultHint' },
      {
        name: 'capabilities',
        labelKey: 'models.fields.capabilities',
        type: 'json',
        default: {},
        rows: 3,
        hintKey: 'models.fields.capabilitiesHint',
      },
    ],
    [providers]
  );

  const api = useMemo(() => ({ ...modelsApi, list: () => modelsApi.list({ limit: MAX_PAGE }) }), []);

  return (
    <CrudPage
      titleKey="models.title"
      api={api}
      columns={columns}
      fields={fields}
      rowClickEdit
      emptyTextKey="models.empty"
      readOnly={readOnly}
    />
  );
};
