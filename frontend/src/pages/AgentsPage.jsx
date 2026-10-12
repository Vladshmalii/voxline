import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { HiSpeakerWave } from 'react-icons/hi2';
import { CrudPage } from 'components/CrudPage';
import { ActiveBadge } from 'components/badges';
import { formatDateTime, SecondaryButton } from 'components/ui';
import { VoiceCatalogModal } from 'components/VoiceCatalogModal';
import { useI18n } from 'contexts/I18nContext';
import { useTheme } from 'contexts/ThemeContext';
import { agentsApi, modelsApi, telephonyApi, MAX_PAGE } from 'utils/callApi';
import { loadModelVoices, voiceLabelForId } from 'utils/voiceCatalog';
import { useVoiceLabels } from 'utils/useVoiceLabels';
import { adminFields, adminTuningFields, basicFields, promptFields, spokenFields, modelFields } from 'pages/agentFields';
import { useUser } from 'contexts/UserContext';
import { canAssignModels, canDeleteAgents, canManageAgents, canPreviewVoice, hasFullAccess } from 'utils/permissions';

const COLUMNS = [
  { key: 'id', labelKey: 'common.id' },
  { key: 'name', labelKey: 'agents.columns.name' },
  { key: 'default_language', labelKey: 'agents.columns.defaultLanguage', align: 'center' },
  { key: 'description', labelKey: 'agents.columns.description', render: (row) => row.description || '—' },
  {
    key: 'is_active',
    labelKey: 'common.status',
    align: 'center',
    render: (row) => <ActiveBadge active={row.is_active} />,
  },
  { key: 'updated_at', labelKey: 'common.updatedAt', render: (row) => formatDateTime(row.updated_at) },
];

export const AgentsPage = () => {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { theme } = useTheme();
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const [defaults, setDefaults] = useState({});
  const readOnly = !canManageAgents(user?.role);
  const canDelete = canDeleteAgents(user?.role);
  const canPreview = canPreviewVoice(user?.role);
  const [refs, setRefs] = useState({ models: [], telephony: [] });
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const isAdmin = hasFullAccess(user?.role);
  const [agentModelIds, setAgentModelIds] = useState([]);
  const voiceLabels = useVoiceLabels(agentModelIds, !canAssign);
  const columns = useMemo(() => COLUMNS.map((column) => column.key === 'tts_voice' && !canAssign ? {
    ...column,
    render: (row) => row.tts_voice ? voiceLabelForId(
      voiceLabels[row.tts_model_id], row.tts_voice, t('agents.fields.currentVoice'), row.default_language
    ) : '—',
  } : column), [canAssign, voiceLabels, t]);

  // The create form's tts_voice field wants a dropdown of the picked TTS
  // model's live voices (when its adapter has a catalogue — see
  // modelsApi.voices); onFormValues tells us which model is currently
  // selected so we can fetch just that one.
  const [voiceModelId, setVoiceModelId] = useState(null);
  const [voiceState, setVoiceState] = useState({ options: [], loading: false });

  useEffect(() => {
    if (!voiceModelId) {
      setVoiceState({ options: [], loading: false });
      return undefined;
    }
    let cancelled = false;
    setVoiceState({ options: [], loading: true });
    loadModelVoices(modelsApi, voiceModelId)
      .then((data) => {
        if (!cancelled) setVoiceState({ options: Array.isArray(data) ? data : [], loading: false });
      })
      .catch(() => {
        if (!cancelled) setVoiceState({ options: [], loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [voiceModelId]);

  // Same for stt_language and the picked STT model (see modelsApi.languages).
  const [sttModelId, setSttModelId] = useState(null);
  const [sttLanguageState, setSttLanguageState] = useState({ options: [], loading: false });

  useEffect(() => {
    if (!sttModelId) {
      setSttLanguageState({ options: [], loading: false });
      return undefined;
    }
    let cancelled = false;
    setSttLanguageState({ options: [], loading: true });
    modelsApi
      .languages(sttModelId)
      .then((data) => {
        if (!cancelled) {
          setSttLanguageState({ options: Array.isArray(data) ? data : [], loading: false });
        }
      })
      .catch(() => {
        // 422 from an adapter with no catalogue — plain text input, as before.
        if (!cancelled) setSttLanguageState({ options: [], loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [sttModelId]);

  const handleFormValues = (values) => {
    const id = canAssign ? (values?.tts_model_id ? Number(values.tts_model_id) : null) : defaults.tts_model_id;
    setVoiceModelId((prev) => (prev === id ? prev : id));
    const sttId = canAssign ? (values?.stt_model_id ? Number(values.stt_model_id) : null) : defaults.stt_model_id;
    setSttModelId((prev) => (prev === sttId ? prev : sttId));
  };

  // The create form picks its STT/TTS/LLM models and the telephony binding
  // from these lookups; tuning stays at the backend defaults and is edited on
  // the agent's own page.
  useEffect(() => {
    const sources = {
      models: canAssign ? modelsApi.list({ limit: MAX_PAGE }) : Promise.resolve([]),
      telephony: canAssign ? telephonyApi.list({ limit: MAX_PAGE }) : Promise.resolve([]),
    };
    Object.entries(sources).forEach(([key, promise]) => {
      promise
        .then((data) => setRefs((prev) => ({ ...prev, [key]: Array.isArray(data) ? data : [] })))
        .catch(() => undefined);
    });
    if (!canAssign) {
      modelsApi.defaults().then((data) => {
        setDefaults(data);
        setVoiceModelId(data.tts_model_id);
        setSttModelId(data.stt_model_id);
      }).catch(() => undefined);
    }
  }, [canAssign]);

  const fields = useMemo(
    () => [
      ...basicFields(),
      ...(isAdmin ? [...adminFields(refs.telephony), ...adminTuningFields()] : []),
      ...promptFields(),
      ...spokenFields(),
      ...modelFields(refs.models, voiceState, sttLanguageState, canAssign),
    ],
    [refs, voiceState, sttLanguageState, canAssign, isAdmin]
  );

  // Editing lives on the agent's page, where the full SVoiceAgentDetailsRead
  // (languages included) is loaded — the list only creates and deletes.
  const api = useMemo(
    () => ({
      list: async () => {
        const rows = await agentsApi.list({ limit: MAX_PAGE });
        setAgentModelIds(rows.map((row) => row.tts_model_id));
        return rows;
      },
      create: agentsApi.create,
      remove: agentsApi.remove,
    }),
    []
  );

  return (
    <>
      <CrudPage
        titleKey="agents.title"
        api={api}
        columns={columns}
        fields={fields}
        onRowClick={(row) => navigate(`/agents/${row.id}`)}
        onFormValues={handleFormValues}
        wideModal
        emptyTextKey="agents.empty"
        readOnly={readOnly}
        canDelete={canDelete}
        headerExtra={
          canPreview && (
            <SecondaryButton
              theme={theme}
              type="button"
              onClick={() => setIsCatalogOpen(true)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            >
              <HiSpeakerWave size={16} />
              <span>{t('agents.testVoicesBtn')}</span>
            </SecondaryButton>
          )
        }
      />
      {canPreview && (
        <VoiceCatalogModal
          isOpen={isCatalogOpen}
          onClose={() => setIsCatalogOpen(false)}
        />
      )}
    </>
  );
};

