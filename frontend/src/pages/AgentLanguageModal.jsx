import { useState, useMemo, useEffect } from 'react';
import { modelFieldsForRole } from 'utils/modelAssignment';
import { useUser } from 'contexts/UserContext';
import { canAssignModels } from 'utils/permissions';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { Modal } from 'components/Modal';
import { toast } from 'components/Toaster';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
import { agentsApi, modelsApi } from 'utils/callApi';
import { loadModelVoices } from 'utils/voiceCatalog';
import { PrimaryButton, SecondaryButton } from 'components/ui';
import {
  modelOptions,
  voiceOptions,
  turnGroup,
  fragmentGroup,
  chunkingGroup,
  vadGroup,
} from 'pages/agentFields';

// SAgentLanguageCreate/Update: everything except `language` is an override —
// unset means "use the agent's default". The nested groups replace whole
// sections when set (see resolve_profile on the backend), so their sub-fields
// carry no `required` of their own: a half-filled group is the backend's 422
// to give, not this form's.
//
// `voiceState` is keyed on whichever tts_model_id is effective for this row —
// its own override if set, else the agent's own model (see
// AgentLanguageModal's effect below) — same modelsApi.voices catalogue the
// agent-level tts_voice field uses.
const languageFields = (models, voiceState, canAssign) => [
  {
    name: 'language',
    labelKey: 'agents.languages.fields.language',
    type: 'text',
    required: true,
    helpKey: 'agents.help.languages.language',
  },
  {
    name: 'voice',
    labelKey: 'agents.languages.fields.voice',
    type: 'voice',
    nullable: true,
    helpKey: canAssign ? 'agents.help.languages.voice' : 'agents.help.clientLanguageVoice',
    allowCustomVoice: canAssign,
    voiceOptions: voiceOptions(voiceState?.options),
    voicesLoading: Boolean(voiceState?.loading),
  },
  {
    name: 'prompts',
    labelKey: 'agents.sections.prompts',
    helpKey: 'agents.help.languages.prompts',
    type: 'object',
    nullable: true,
    fields: [
      { name: 'system_prompt', labelKey: 'agents.languages.fields.systemPrompt', type: 'textarea', rows: 6, helpKey: 'agents.help.systemPrompt' },
      { name: 'call_script', labelKey: 'agents.languages.fields.callScript', type: 'textarea', rows: 4, emptyValue: '', helpKey: 'agents.help.callScript' },
      { name: 'greeting_kickoff', labelKey: 'agents.languages.fields.greetingKickoff', type: 'textarea', rows: 2, emptyValue: '', helpKey: 'agents.help.greetingKickoff' },
    ],
  },
  {
    name: 'spoken',
    labelKey: 'agents.sections.spoken',
    helpKey: 'agents.help.languages.spoken',
    type: 'object',
    nullable: true,
    fields: [
      { name: 'silence', labelKey: 'agents.fields.spokenSilence', type: 'text', helpKey: 'agents.help.spokenSilence' },
      { name: 'reprompt', labelKey: 'agents.fields.spokenReprompt', type: 'text', helpKey: 'agents.help.spokenReprompt' },
      { name: 'goodbye', labelKey: 'agents.fields.spokenGoodbye', type: 'text', helpKey: 'agents.help.spokenGoodbye' },
      { name: 'no_answer', labelKey: 'agents.fields.spokenNoAnswer', type: 'text', emptyValue: '', helpKey: 'agents.help.spokenNoAnswer' },
    ],
  },
  {
    name: 'stt_model_id',
    labelKey: 'agents.languages.fields.sttModel',
    type: 'select',
    asNumber: true,
    nullable: true,
    emptyLabelKey: 'agents.languages.none',
    options: modelOptions(models, 'stt'),
    helpKey: 'agents.help.languages.model',
  },
  {
    name: 'tts_model_id',
    labelKey: 'agents.languages.fields.ttsModel',
    type: 'select',
    asNumber: true,
    nullable: true,
    emptyLabelKey: 'agents.languages.none',
    options: modelOptions(models, 'tts'),
    helpKey: 'agents.help.languages.model',
  },
  {
    name: 'ttt_model_id',
    labelKey: 'agents.languages.fields.tttModel',
    type: 'select',
    asNumber: true,
    nullable: true,
    emptyLabelKey: 'agents.languages.none',
    options: modelOptions(models, 'ttt'),
    helpKey: 'agents.help.languages.model',
  },
  {
    name: 'stt_params',
    labelKey: 'agents.languages.fields.sttParams',
    type: 'json',
    nullable: true,
    rows: 3,
    helpKey: 'agents.help.languages.sttParams',
  },
  {
    name: 'tts_params',
    labelKey: 'agents.languages.fields.ttsParams',
    type: 'json',
    nullable: true,
    rows: 3,
    helpKey: 'agents.help.languages.ttsParams',
  },
  {
    name: 'ttt_params',
    labelKey: 'agents.languages.fields.tttParams',
    type: 'json',
    nullable: true,
    rows: 3,
    helpKey: 'agents.help.languages.tttParams',
  },
  turnGroup(),
  fragmentGroup(),
  chunkingGroup(),
  vadGroup(),
];

/** Create or edit one SAgentLanguage row of `agentId`. */
export const AgentLanguageModal = ({
  agentId,
  row,
  models,
  agentTtsModelId,
  onClose,
  onSaved,
}) => {
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const { theme } = useTheme();
  const { t } = useI18n();

  const [voiceState, setVoiceState] = useState({ options: [], loading: false });
  const fields = useMemo(() => modelFieldsForRole(languageFields(models, voiceState, canAssign), canAssign), [models, voiceState, canAssign]);
  const [values, setValues] = useState(() => buildInitialValues(fields, row || null));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // This row's own tts_model_id override wins; unset means the agent's own
    // model is what a call would actually use for this language.
    const id = canAssign
      ? Number(values.tts_model_id) || agentTtsModelId || null
      : row?.tts_model_id || agentTtsModelId || null;
    if (!id) {
      setVoiceState({ options: [], loading: false });
      return undefined;
    }
    let cancelled = false;
    setVoiceState({ options: [], loading: true });
    loadModelVoices(modelsApi, id)
      .then((data) => {
        if (!cancelled) setVoiceState({ options: Array.isArray(data) ? data : [], loading: false });
      })
      .catch(() => {
        if (!cancelled) setVoiceState({ options: [], loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values.tts_model_id, agentTtsModelId, row?.tts_model_id, canAssign]);

  const save = async () => {
    const { payload, errors: nextErrors } = buildPayload(fields, values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setSaving(true);
    try {
      const saved = row
        ? await agentsApi.updateLanguage(agentId, row.id, payload)
        : await agentsApi.createLanguage(agentId, payload);
      toast(t('agents.languages.saved'), 'success');
      onSaved(saved);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      wide
      title={row ? t('agents.languages.editTitle', { language: row.language }) : t('agents.languages.addTitle')}
      onClose={onClose}
      footer={
        <>
          <SecondaryButton theme={theme} type="button" onClick={onClose}>
            {t('common.cancel')}
          </SecondaryButton>
          <PrimaryButton theme={theme} type="button" disabled={saving} onClick={save}>
            {saving ? t('common.saving') : t('common.save')}
          </PrimaryButton>
        </>
      }
    >
      <ResourceForm fields={fields} values={values} errors={errors} onChange={setValues} />
    </Modal>
  );
};
