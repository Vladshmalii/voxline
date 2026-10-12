import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import styled, { keyframes } from 'styled-components';
import {
  HiArrowLeft,
  HiCog6Tooth,
  HiPlus,
  HiPencil,
  HiTrash,
  HiPlay,
  HiSpeakerWave,
  HiStop,
  HiArrowPath,
} from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { toast } from 'components/Toaster';
import { Modal } from 'components/Modal';
import { RefreshButton } from 'components/RefreshButton';
import { ActiveBadge } from 'components/badges';
import { AgentSettingsModal } from 'pages/AgentSettingsModal';
import { AgentLanguageModal } from 'pages/AgentLanguageModal';
import { agentsApi, modelsApi, telephonyApi, messagingApi, MAX_PAGE } from 'utils/callApi';
import { voiceLabelForId } from 'utils/voiceCatalog';
import { useVoiceLabels } from 'utils/useVoiceLabels';
import { useUser } from 'contexts/UserContext';
import { canAssignModels, canDeleteAgents, canManageAgents, canPreviewVoice } from 'utils/permissions';
import {
  PageContent,
  HeaderSection,
  PageTitle,
  HeaderActions,
  ContentScroll,
  PrimaryButton,
  SecondaryButton,
  DangerButton,
  Select,
  TextInput,
  Badge,
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
  formatDateTime,
} from 'components/ui';

// Deliberately minimal (per review): this page used to also carry a full
// model/telephony overview grid, a readiness probe and a resolved-profile
// JSON preview. All three are cut — the only things an operator actually
// comes here for are the prompt driving the agent, its per-language rows,
// when it last changed, and a quick way to hear the voice. Editing
// everything else (models, spoken lines, tuning) still lives in the
// "Настройки" modal (AgentSettingsModal) — this page is a read surface, not
// a second edit form.

const Section = styled.section`
  max-width: 900px;
  margin-bottom: 28px;
`;

const SectionHead = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
`;

const SectionTitle = styled.h3`
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: ${({ theme }) => theme.colors.secondary};
`;

const SectionHint = styled.p`
  margin: 0 0 12px;
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const MetaLine = styled.div`
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const VoiceTestRow = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;

  select {
    width: auto;
    min-width: 160px;
  }

  input {
    flex: 1;
    min-width: 220px;
  }
`;

const spin = keyframes`
  to { transform: rotate(360deg); }
`;

const VoicePlayButton = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 8px;
  border: 1px solid ${({ theme, $active }) => ($active ? theme.colors.accentNeon || theme.colors.accent : theme.colors.border)};
  background: ${({ theme, $active }) => ($active ? `${theme.colors.accent}18` : theme.colors.surface)};
  color: ${({ theme, $active }) => ($active ? theme.colors.accentNeon || theme.colors.primary : theme.colors.primary)};
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;

  svg.spin {
    animation: ${spin} 0.8s linear infinite;
  }

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.colors.accentNeon || theme.colors.primary};
  }

  &:disabled {
    opacity: 0.6;
    cursor: wait;
  }
`;

const RowVoiceButton = styled(RowActionButton)`
  color: ${({ theme, $active }) => ($active ? theme.colors.accentNeon || theme.colors.primary : undefined)};
`;

// Which of a language row's override slots are set — for the list column.
const OVERRIDE_SLOTS = [
  'voice',
  'prompts',
  'spoken',
  'turn',
  'fragment',
  'chunking',
  'vad',
  'stt_model_id',
  'tts_model_id',
  'ttt_model_id',
  'stt_params',
  'tts_params',
  'ttt_params',
];

const overrideSummary = (row) =>
  OVERRIDE_SLOTS.filter((slot) => row[slot] !== null && row[slot] !== undefined).join(', ');

export const AgentDetailsPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const { agentId } = useParams();
  const navigate = useNavigate();
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const canManage = canManageAgents(user?.role);
  const canDelete = canDeleteAgents(user?.role);
  const canPreview = canPreviewVoice(user?.role);

  const [agent, setAgent] = useState(null);
  const voiceLabels = useVoiceLabels((agent?.languages || [])
    .filter((row) => row.voice)
    .map((row) => row.tts_model_id || agent.tts_model_id), !canAssign);
  const [refs, setRefs] = useState({ models: [], telephony: [], messaging: [] });
  const [loadError, setLoadError] = useState(null);
  const [modal, setModal] = useState(null); // { kind: 'settings'|'language', row? }
  const [deleting, setDeleting] = useState(null); // language row pending confirm
  const [busy, setBusy] = useState(false);

  // Voice test — inline, not a modal: `voicePlayingKey`/`voiceLoadingKey` are
  // either 'test' (the widget below) or a language code (a language row's own
  // preview button), so the two never fight over one piece of state.
  const [voicePlayingKey, setVoicePlayingKey] = useState(null);
  const [voiceLoadingKey, setVoiceLoadingKey] = useState(null);
  const [testLanguage, setTestLanguage] = useState('');
  const [testText, setTestText] = useState('');
  const audioRef = useRef(null);

  useEffect(() => {
    audioRef.current = new Audio();
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = '';
      }
    };
  }, []);

  const toggleVoicePlay = async (key, { language, text } = {}) => {
    const audio = audioRef.current;
    if (!audio || !agent) return;

    if (voicePlayingKey === key) {
      audio.pause();
      setVoicePlayingKey(null);
      return;
    }

    setVoiceLoadingKey(key);
    try {
      const audioUrl = await agentsApi.previewVoice(agent.id, {
        language: language || undefined,
        text: text || undefined,
      });
      audio.pause();
      audio.src = audioUrl;
      audio.onended = () => setVoicePlayingKey(null);
      audio.onerror = () => {
        toast(t('common.failedToLoad'), 'error');
        setVoicePlayingKey(null);
      };
      await audio.play();
      setVoicePlayingKey(key);
    } catch (e) {
      toast(e.message, 'error');
      setVoicePlayingKey(null);
    } finally {
      setVoiceLoadingKey(null);
    }
  };

  const [reloading, setReloading] = useState(false);
  const load = useCallback(async () => {
    setLoadError(null);
    setReloading(true);
    try {
      setAgent(await agentsApi.get(agentId));
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setReloading(false);
    }
  }, [agentId]);

  useEffect(() => {
    load();
  }, [load]);

  // Model/telephony/messaging rows are still needed by the settings and
  // language modals' own selects — this page no longer displays them itself.
  useEffect(() => {
    const sources = {
      models: canAssign ? modelsApi.list({ limit: MAX_PAGE }) : Promise.resolve([]),
      telephony: canAssign ? telephonyApi.list({ limit: MAX_PAGE }) : Promise.resolve([]),
      messaging: canAssign ? messagingApi.list({ limit: MAX_PAGE }) : Promise.resolve([]),
    };
    Object.entries(sources).forEach(([key, promise]) => {
      promise
        .then((data) => setRefs((prev) => ({ ...prev, [key]: Array.isArray(data) ? data : [] })))
        .catch(() => undefined);
    });
  }, [canAssign]);

  const agentSaved = (updated) => {
    setAgent(updated);
    setModal(null);
  };

  const languageSaved = (saved) => {
    setAgent((prev) => ({
      ...prev,
      languages: prev.languages.some((x) => x.id === saved.id)
        ? prev.languages.map((x) => (x.id === saved.id ? saved : x))
        : [...prev.languages, saved],
    }));
    setModal(null);
  };

  const confirmDeleteLanguage = async () => {
    setBusy(true);
    try {
      await agentsApi.removeLanguage(agent.id, deleting.id);
      toast(t('agents.languages.deleted'), 'success');
      setAgent((prev) => ({ ...prev, languages: prev.languages.filter((x) => x.id !== deleting.id) }));
      setDeleting(null);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  const languageOptions = useMemo(() => agent?.languages ?? [], [agent]);

  if (loadError) {
    return (
      <PageContent>
        <EmptyState theme={theme}>
          <EmptyStateTitle theme={theme}>{t('common.failedToLoad')}</EmptyStateTitle>
          <EmptyStateText theme={theme}>{loadError}</EmptyStateText>
        </EmptyState>
      </PageContent>
    );
  }

  if (!agent) {
    return (
      <PageContent>
        <EmptyState theme={theme}>{t('common.loading')}</EmptyState>
      </PageContent>
    );
  }

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <HeaderActions>
          <SecondaryButton theme={theme} type="button" onClick={() => navigate('/agents')}>
            <HiArrowLeft size={15} /> {t('agents.backToAgents')}
          </SecondaryButton>
          <PageTitle theme={theme}>{agent.name}</PageTitle>
          <ActiveBadge active={agent.is_active} />
          <MetaLine theme={theme}>
            {t('agents.info.updated')}: {formatDateTime(agent.updated_at)}
          </MetaLine>
        </HeaderActions>
        <HeaderActions>
          {canManage && (
            <SecondaryButton theme={theme} type="button" onClick={() => setModal({ kind: 'settings' })}>
              <HiCog6Tooth size={15} /> {t('agents.settings')}
            </SecondaryButton>
          )}
          {canPreview && (
            <PrimaryButton
              theme={theme}
              type="button"
              onClick={() => navigate(`/agents/${agent.id}/playground`)}
            >
              <HiPlay size={15} /> {t('agents.playground')}
            </PrimaryButton>
          )}
          <RefreshButton onClick={load} loading={reloading} />
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        {canPreview && (
        <Section>
          <SectionTitle theme={theme}>{t('agents.voiceTest.section')}</SectionTitle>
          <VoiceTestRow>
            <Select theme={theme} value={testLanguage} onChange={(e) => setTestLanguage(e.target.value)}>
              <option value="">{t('agents.voiceTest.defaultOption', { language: agent.default_language })}</option>
              {languageOptions.map((row) => (
                <option key={row.id} value={row.language}>
                  {row.language}
                </option>
              ))}
            </Select>
            <TextInput
              theme={theme}
              type="text"
              value={testText}
              placeholder={t('agents.voiceTest.textPlaceholder')}
              onChange={(e) => setTestText(e.target.value)}
            />
            <VoicePlayButton
              theme={theme}
              type="button"
              $active={voicePlayingKey === 'test'}
              disabled={voiceLoadingKey === 'test'}
              onClick={() => toggleVoicePlay('test', { language: testLanguage, text: testText })}
            >
              {voiceLoadingKey === 'test' ? (
                <>
                  <HiArrowPath className="spin" size={13} />
                  {t('agents.voiceTest.synthesizing')}
                </>
              ) : voicePlayingKey === 'test' ? (
                <>
                  <HiStop size={13} /> {t('agents.voiceTest.stop')}
                </>
              ) : (
                <>
                  <HiSpeakerWave size={13} /> {t('agents.voiceTest.play')}
                </>
              )}
            </VoicePlayButton>
          </VoiceTestRow>
        </Section>
        )}

        <Section>
          <SectionHead>
            <SectionTitle theme={theme} style={{ margin: 0 }}>
              {t('agents.languages.section')}
            </SectionTitle>
            {canManage && (
              <SecondaryButton theme={theme} type="button" onClick={() => setModal({ kind: 'language' })}>
                <HiPlus size={14} /> {t('agents.languages.add')}
              </SecondaryButton>
            )}
          </SectionHead>
          <SectionHint theme={theme}>{t('agents.languages.hint')}</SectionHint>

          {agent.languages.length === 0 ? (
            <EmptyStateText theme={theme}>{t('agents.languages.empty')}</EmptyStateText>
          ) : (
            <TableContainer theme={theme}>
              <Table>
                <TableHeader theme={theme}>
                  <tr>
                    <TableHeaderCell theme={theme}>{t('agents.languages.columns.language')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('agents.languages.columns.voice')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('agents.languages.columns.overrides')}</TableHeaderCell>
                    <TableHeaderCell theme={theme}>{t('common.updatedAt')}</TableHeaderCell>
                    <TableHeaderCell theme={theme} $align="right">
                      {t('common.actions')}
                    </TableHeaderCell>
                  </tr>
                </TableHeader>
                <tbody>
                  {agent.languages.map((row) => (
                    <TableRow key={row.id} theme={theme}>
                      <TableCell theme={theme}>
                        <Badge $color={theme.colors.accent}>{row.language}</Badge>
                      </TableCell>
                      <TableCell theme={theme}>
                        {row.voice ? (canAssign ? row.voice : voiceLabelForId(
                          voiceLabels[row.tts_model_id || agent.tts_model_id], row.voice,
                          t('agents.fields.currentVoice'), row.language
                        )) : t('agents.languages.none')}
                      </TableCell>
                      <TableCell theme={theme}>{overrideSummary(row) || t('agents.languages.none')}</TableCell>
                      <TableCell theme={theme}>{formatDateTime(row.updated_at)}</TableCell>
                      <TableCell theme={theme} $align="right">
                        <RowActions style={{ justifyContent: 'flex-end' }}>
                          {canPreview && (
                            <RowVoiceButton
                              theme={theme}
                              type="button"
                              $active={voicePlayingKey === row.language}
                              disabled={voiceLoadingKey === row.language}
                              onClick={() => toggleVoicePlay(row.language, { language: row.language })}
                              title={t('agents.voiceTest.play')}
                            >
                              {voiceLoadingKey === row.language ? (
                                <HiArrowPath className="spin" size={12} />
                              ) : voicePlayingKey === row.language ? (
                                <HiStop size={12} />
                              ) : (
                                <HiSpeakerWave size={12} />
                              )}
                            </RowVoiceButton>
                          )}
                          {canManage && (
                            <RowActionButton
                              theme={theme}
                              type="button"
                              onClick={() => setModal({ kind: 'language', row })}
                            >
                              <HiPencil size={12} /> {t('common.edit')}
                            </RowActionButton>
                          )}
                          {canDelete && (
                            <RowActionButton theme={theme} type="button" $danger onClick={() => setDeleting(row)}>
                              <HiTrash size={12} /> {t('common.remove')}
                            </RowActionButton>
                          )}
                        </RowActions>
                      </TableCell>
                    </TableRow>
                  ))}
                </tbody>
              </Table>
            </TableContainer>
          )}
        </Section>
      </ContentScroll>

      {modal?.kind === 'settings' && (
        <AgentSettingsModal agent={agent} refs={refs} onClose={() => setModal(null)} onSaved={agentSaved} />
      )}

      {modal?.kind === 'language' && (
        <AgentLanguageModal
          agentId={agent.id}
          row={modal.row}
          models={refs.models}
          agentTtsModelId={agent.tts_model_id}
          onClose={() => setModal(null)}
          onSaved={languageSaved}
        />
      )}

      {deleting && (
        <Modal
          title={t('agents.languages.deleteTitle', { language: deleting.language })}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <SecondaryButton theme={theme} type="button" onClick={() => setDeleting(null)}>
                {t('common.cancel')}
              </SecondaryButton>
              <DangerButton theme={theme} type="button" disabled={busy} onClick={confirmDeleteLanguage}>
                {busy ? t('common.removing') : t('common.remove')}
              </DangerButton>
            </>
          }
        >
          <EmptyStateText theme={theme}>{t('common.irreversible')}</EmptyStateText>
        </Modal>
      )}
    </PageContent>
  );
};
