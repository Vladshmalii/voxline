import { useState, useMemo, useEffect } from 'react';
import { useUser } from 'contexts/UserContext';
import { canAssignModels, hasFullAccess } from 'utils/permissions';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { Modal } from 'components/Modal';
import { toast } from 'components/Toaster';
import { ResourceForm, buildInitialValues, buildPayload } from 'components/ResourceForm';
import { agentsApi, modelsApi } from 'utils/callApi';
import { loadModelVoices } from 'utils/voiceCatalog';
import { PrimaryButton, SecondaryButton, FieldHint } from 'components/ui';
import {
  adminFields,
  adminTuningFields,
  basicFields,
  promptFields,
  spokenFields,
  modelFields,
  smsToolFields,
  turnGroup,
  fragmentGroup,
  chunkingGroup,
  vadGroup,
  languageSwitchGroup,
  silenceFeedbackGroup,
  spokenFeedbackField,
} from 'pages/agentFields';

const SectionTitle = styled.h3`
  margin: 20px 0 10px;
  font-size: 13px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.secondary};

  &:first-child {
    margin-top: 0;
  }
`;

const SectionHint = styled.p`
  margin: -4px 0 10px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;

// VOAD-62: "На модерации" — the SMS-tool text is staff-authored and not yet
// signed off, so the engine won't offer the tool to the model at all.
const PendingBadge = styled.span`
  display: inline-block;
  margin: -4px 0 10px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 600;
  border-radius: ${({ theme }) => theme.radii.pill};
  color: #D97706;
  background: #D9770622;
  border: 1px solid #D9770655;
`;

/**
 * The full SVoiceAgentUpdate surface, grouped into sections. Every section
 * shares one values map (field names never collide), so a single buildPayload
 * over the concatenated specs makes the PATCH body.
 */
export const AgentSettingsModal = ({ agent, refs, onClose, onSaved }) => {
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const isAdmin = hasFullAccess(user?.role);
  const { theme } = useTheme();
  const { t } = useI18n();

  // The Models section's tts_voice field wants a dropdown of the picked TTS
  // model's live voices (see modelsApi.voices) — fetched for whichever model
  // is currently selected, not the one the agent was saved with.
  const [voiceState, setVoiceState] = useState({ options: [], loading: false });
  // Same for stt_language and the picked STT model (see modelsApi.languages).
  const [sttLanguageState, setSttLanguageState] = useState({ options: [], loading: false });

  const sections = useMemo(
    () => [
      { titleKey: 'agents.sections.basic', fields: basicFields() },
      { titleKey: 'agents.sections.prompts', fields: promptFields() },
      { titleKey: 'agents.sections.spoken', fields: [...spokenFields(), ...spokenFeedbackField()] },
      {
        titleKey: 'agents.sections.models',
        fields: modelFields(refs.models, voiceState, sttLanguageState, canAssign),
      },
      {
        titleKey: 'agents.sections.smsTool',
        fields: smsToolFields(refs.messaging, canAssign),
        pendingModeration: agent.sms_tool_message_status === 'pending',
      },
      // Admin logic: per-agent technical limits, telephony and conversation
      // tuning. Not even rendered for other roles, so their PATCH never
      // carries these fields (the backend refuses them with 403 anyway).
      ...(isAdmin
        ? [
            {
              titleKey: 'agents.logic.admin',
              hintKey: 'agents.logic.adminHint',
              fields: [...adminFields(refs.telephony), ...adminTuningFields()],
            },
            // The tuning groups are single object fields — their titles come
            // from the field labels, so no section header of their own.
            {
              fields: [
                silenceFeedbackGroup(),
                turnGroup(),
                fragmentGroup(),
                chunkingGroup(),
                vadGroup(),
                languageSwitchGroup(),
              ],
            },
          ]
        : []),
    ],
    [refs, agent, voiceState, sttLanguageState, canAssign, isAdmin]
  );

  const allFields = useMemo(() => sections.flatMap((s) => s.fields), [sections]);

  // `messaging_id: null` is ambiguous once the organization has more than one
  // active SMS route — the backend then refuses to send until one is named.
  const activeMessagingCount = useMemo(
    () => (refs.messaging || []).filter((r) => r.is_active).length,
    [refs.messaging]
  );

  const [values, setValues] = useState(() => buildInitialValues(allFields, agent));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const id = canAssign ? Number(values.tts_model_id) || null : agent.tts_model_id;
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
  }, [values.tts_model_id, canAssign, agent.tts_model_id]);

  useEffect(() => {
    const id = canAssign ? Number(values.stt_model_id) || null : agent.stt_model_id;
    if (!id) {
      setSttLanguageState({ options: [], loading: false });
      return undefined;
    }
    let cancelled = false;
    setSttLanguageState({ options: [], loading: true });
    modelsApi
      .languages(id)
      .then((data) => {
        if (!cancelled) {
          setSttLanguageState({ options: Array.isArray(data) ? data : [], loading: false });
        }
      })
      .catch(() => {
        if (!cancelled) setSttLanguageState({ options: [], loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values.stt_model_id, canAssign, agent.stt_model_id]);

  const save = async () => {
    const { payload, errors: nextErrors } = buildPayload(allFields, values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setSaving(true);
    try {
      const updated = await agentsApi.update(agent.id, payload);
      toast(t('agents.settingsSaved'), 'success');
      onSaved(updated);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      wide
      title={t('agents.settingsTitle', { id: agent.id })}
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
      <SectionTitle theme={theme}>{t('agents.logic.client')}</SectionTitle>
      {sections.map((section, i) => (
        <div key={section.titleKey || i}>
          {section.titleKey && <SectionTitle theme={theme}>{t(section.titleKey)}</SectionTitle>}
          {section.pendingModeration && (
            <div>
              <PendingBadge theme={theme}>{t('agents.fields.smsToolModerationPending')}</PendingBadge>
            </div>
          )}
          {section.hintKey && <SectionHint theme={theme}>{t(section.hintKey)}</SectionHint>}
          <ResourceForm fields={section.fields} values={values} errors={errors} onChange={setValues} />
          {section.titleKey === 'agents.sections.smsTool' &&
            canAssign &&
            values.sms_tool_enabled &&
            activeMessagingCount >= 2 &&
            !values.messaging_id && (
              <FieldHint theme={theme} $error>
                {t('agents.help.messagingRouteAmbiguous')}
              </FieldHint>
            )}
        </div>
      ))}
    </Modal>
  );
};
