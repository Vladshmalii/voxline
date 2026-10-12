import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useUser } from 'contexts/UserContext';
import { canAssignModels } from 'utils/permissions';
import styled, { keyframes } from 'styled-components';
import {
  HiPlay,
  HiClipboardDocument,
  HiCheck,
  HiMagnifyingGlass,
  HiArrowPath,
  HiSpeakerWave,
} from 'react-icons/hi2';
import { Modal } from 'components/Modal';
import { toast } from 'components/Toaster';
import { useI18n } from 'contexts/I18nContext';
import { useTheme } from 'contexts/ThemeContext';
import { agentsApi, modelsApi } from 'utils/callApi';
import { loadVoiceCatalog, voicePreviewRequest } from 'utils/voiceCatalog';
import { DEFAULT_PIE_SELLER_PHRASE } from '../data/voicesCatalog';
import {
  SecondaryButton,
  FieldHint,
  Table,
  TableHeader,
  TableHeaderCell,
  TableRow,
  TableCell,
  TableContainer,
} from 'components/ui';

const pulse = keyframes`
  0%, 100% { transform: scaleY(0.4); }
  50% { transform: scaleY(1); }
`;

const spin = keyframes`
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
`;

const Spinner = styled.span`
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: ${spin} 0.6s linear infinite;
`;

const SoundWave = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 14px;

  span {
    display: inline-block;
    width: 3px;
    height: 100%;
    background: currentColor;
    border-radius: ${({ theme }) => theme.radii.xs};
    animation: ${pulse} 0.8s ease-in-out infinite;

    &:nth-child(2) {
      animation-delay: 0.15s;
    }
    &:nth-child(3) {
      animation-delay: 0.3s;
    }
  }
`;

const CatalogContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 16px;
`;

const HeaderSubtitle = styled.p`
  margin: 0;
  font-size: 13px;
  line-height: 1.45;
  color: ${({ theme }) => theme.colors.secondary};
`;

const PhraseBox = styled.div`
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const PhraseBoxHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
`;

const PhraseLabel = styled.label`
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  display: flex;
  align-items: center;
  gap: 6px;
`;

const ResetButton = styled.button`
  background: none;
  border: none;
  color: ${({ theme }) => theme.colors.secondary};
  font-size: 12px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: ${({ theme }) => theme.radii.xs};
  transition: all 0.15s ease;

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
    background: ${({ theme }) => theme.colors.hover};
  }
`;

const PhraseTextarea = styled.textarea`
  width: 100%;
  min-height: 54px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.45;
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.primary};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  resize: vertical;
  box-sizing: border-box;
  font-family: inherit;

  &:focus {
    outline: none;
    border-color: #2563EB;
  }
`;

const FilterBar = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
`;

const SearchInputWrapper = styled.div`
  position: relative;
  flex: 1;
  min-width: 220px;
`;

const SearchIcon = styled(HiMagnifyingGlass)`
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: ${({ theme }) => theme.colors.secondary};
  pointer-events: none;
`;

const SearchInput = styled.input`
  width: 100%;
  height: 36px;
  padding: 0 12px 0 34px;
  font-size: 13px;
  background: ${({ theme }) => theme.colors.background};
  color: ${({ theme }) => theme.colors.primary};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  box-sizing: border-box;

  &:focus {
    outline: none;
    border-color: #2563EB;
  }
`;

const Select = styled.select`
  height: 36px;
  padding: 0 28px 0 10px;
  font-size: 13px;
  background: ${({ theme }) => theme.colors.background};
  color: ${({ theme }) => theme.colors.primary};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;

  &:focus {
    outline: none;
    border-color: #2563EB;
  }
`;

const ProviderTag = styled.span`
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
`;

const ModelSubtitle = styled.div`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
`;

const VoiceNameWrapper = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.primary};
`;

const VoiceIdPill = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: ${({ theme }) => theme.colors.background};
  color: ${({ theme, $copied }) => ($copied ? '#16A34A' : theme.colors.primary)};
  border: 1px solid ${({ theme, $copied }) => ($copied ? '#16A34A' : theme.colors.border)};
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.15s ease;

  &:hover {
    background: ${({ theme }) => theme.colors.hover};
    border-color: #2563EB;
  }
`;

const PlayButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: ${({ theme }) => theme.radii.sm};
  border: 1px solid ${({ $active }) => ($active ? '#DC2626' : '#2563EB')};
  background: ${({ $active }) => ($active ? '#FEE2E2' : '#EFF6FF')};
  color: ${({ $active }) => ($active ? '#991B1B' : '#1D4ED8')};
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;

  &:hover {
    background: ${({ $active }) => ($active ? '#FECACA' : '#DBEAFE')};
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
`;

const LangBadge = styled.span`
  font-size: 12px;
  font-weight: 600;
  padding: 2px 5px;
  border-radius: ${({ theme }) => theme.radii.xs};
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  color: ${({ theme }) => theme.colors.secondary};
  margin-right: 4px;
`;

export const VoiceCatalogModal = ({ isOpen, onClose }) => {
  const user = useUser();
  const canAssign = canAssignModels(user?.role);
  const { t } = useI18n();
  const { theme } = useTheme();

  const [phrase, setPhrase] = useState(DEFAULT_PIE_SELLER_PHRASE);
  const [search, setSearch] = useState('');
  const [selectedModel, setSelectedModel] = useState('all');
  const [selectedLanguage, setSelectedLanguage] = useState('all');
  const [copiedId, setCopiedId] = useState(null);

  const [catalog, setCatalog] = useState({ voices: [], errors: [], hasModels: false });
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [activeVoiceId, setActiveVoiceId] = useState(null);
  const [loadingVoiceId, setLoadingVoiceId] = useState(null);

  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);

  const playbackRequest = useRef(0);

  const stopAudio = useCallback(() => {
    playbackRequest.current += 1;
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setActiveVoiceId(null);
    setLoadingVoiceId(null);
  }, []);

  useEffect(() => {
    stopAudio();
    if (!isOpen) return;
    let cancelled = false;
    setCatalogLoading(true);
    setCatalog({ voices: [], errors: [], hasModels: false });
    setSelectedModel('all');
    setSelectedLanguage('all');
    loadVoiceCatalog(modelsApi, canAssign, { force: reloadKey > 0 })
      .then((data) => { if (!cancelled) setCatalog(data); })
      .catch((error) => {
        if (!cancelled) setCatalog({ voices: [], errors: [error.message], hasModels: false });
      })
      .finally(() => { if (!cancelled) setCatalogLoading(false); });
    return () => { cancelled = true; stopAudio(); };
  }, [isOpen, canAssign, reloadKey, stopAudio]);

  const handleCopyId = (voiceId, e) => {
    e?.stopPropagation();
    navigator.clipboard?.writeText(voiceId);
    setCopiedId(voiceId);
    toast(t('agents.catalog.copySuccess'), 'success');
    setTimeout(() => {
      setCopiedId((prev) => (prev === voiceId ? null : prev));
    }, 2000);
  };

  const handlePlayVoice = async (item) => {
    if (activeVoiceId === item.id) {
      stopAudio();
      return;
    }

    stopAudio();
    const requestId = playbackRequest.current;
    setLoadingVoiceId(item.id);

    try {
      // Extract voice first name for {name} placeholder
      const cleanName = item.name.split(' ')[0].replace(/[^a-zA-Zа-яА-ЯёЁ]/g, '');
      const dynamicPhrase = (phrase || DEFAULT_PIE_SELLER_PHRASE).replace(
        /\{\{name\}\}|\{name\}/gi,
        cleanName || item.name
      );

      const url = await agentsApi.previewVoiceDirect(voicePreviewRequest(item, dynamicPhrase, canAssign));
      if (requestId !== playbackRequest.current) {
        URL.revokeObjectURL(url);
        return;
      }

      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onended = () => {
        stopAudio();
      };
      audio.onerror = () => {
        stopAudio();
        toast(t('agents.catalog.playbackError'), 'error');
      };

      await audio.play();
      if (requestId === playbackRequest.current) setActiveVoiceId(item.id);
    } catch (err) {
      if (requestId === playbackRequest.current) {
        toast(canAssign ? err.message || t('agents.catalog.playbackError') : t('agents.catalog.playbackError'), 'error');
        stopAudio();
      }
    } finally {
      if (requestId === playbackRequest.current) setLoadingVoiceId(null);
    }
  };

  const models = useMemo(() =>
    [...new Map(catalog.voices.map((voice) => [voice.modelId, voice.modelName])).entries()],
  [catalog.voices]);
  const languages = useMemo(() =>
    [...new Set(catalog.voices.flatMap((voice) => voice.languages))].sort(),
  [catalog.voices]);

  const filteredVoices = useMemo(() => catalog.voices.filter((voice) => {
    if (canAssign && selectedModel !== 'all' && String(voice.modelId) !== selectedModel) return false;
    if (selectedLanguage !== 'all' && !voice.languages.includes(selectedLanguage)) return false;
    const query = search.trim().toLowerCase();
    const searchable = [voice.name, ...voice.languages];
    if (canAssign) searchable.push(voice.voiceId, voice.modelName, voice.modelCode, voice.adapter);
    return !query || searchable.some((value) => value?.toLowerCase().includes(query));
  }), [catalog.voices, selectedModel, selectedLanguage, search, canAssign]);

  if (!isOpen) return null;

  return (
    <Modal
      title={t('agents.catalog.title')}
      onClose={() => {
        stopAudio();
        onClose();
      }}
      wide
      width="1060px"
      footer={
        <SecondaryButton
          theme={theme}
          type="button"
          onClick={() => {
            stopAudio();
            onClose();
          }}
        >
          {t('common.close')}
        </SecondaryButton>
      }
    >
      <CatalogContainer>
        <HeaderSubtitle theme={theme}>{t(canAssign ? 'agents.catalog.subtitle' : 'agents.catalog.clientSubtitle')}</HeaderSubtitle>

        {/* Phrase customizer */}
        <PhraseBox theme={theme}>
          <PhraseBoxHeader>
            <PhraseLabel theme={theme}>
              <HiSpeakerWave size={15} />
              {t('agents.catalog.testPhraseLabel')}
            </PhraseLabel>
            {phrase !== DEFAULT_PIE_SELLER_PHRASE && (
              <ResetButton
                theme={theme}
                type="button"
                onClick={() => setPhrase(DEFAULT_PIE_SELLER_PHRASE)}
              >
                <HiArrowPath size={13} />
                {t('agents.catalog.resetPhrase')}
              </ResetButton>
            )}
          </PhraseBoxHeader>
          <PhraseTextarea
            theme={theme}
            value={phrase}
            onChange={(e) => setPhrase(e.target.value)}
            placeholder={DEFAULT_PIE_SELLER_PHRASE}
          />
        </PhraseBox>

        {/* Filter bar */}
        <FilterBar>
          <SearchInputWrapper>
            <SearchIcon theme={theme} size={16} />
            <SearchInput
              theme={theme}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t(canAssign ? 'agents.catalog.searchPlaceholder' : 'agents.catalog.clientSearchPlaceholder')}
            />
          </SearchInputWrapper>

          {canAssign && (
            <Select
              theme={theme}
              aria-label={t('agents.catalog.allModels')}
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              <option value="all">{t('agents.catalog.allModels')}</option>
              {models.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </Select>
          )}
          <Select
            theme={theme}
            aria-label={t('agents.catalog.allLanguages')}
            value={selectedLanguage}
            onChange={(e) => setSelectedLanguage(e.target.value)}
          >
            <option value="all">{t('agents.catalog.allLanguages')}</option>
            {languages.map((language) => <option key={language} value={language}>{language}</option>)}
          </Select>
          <SecondaryButton theme={theme} type="button" disabled={catalogLoading} onClick={() => setReloadKey((key) => key + 1)}>
            {t('agents.catalog.refresh')}
          </SecondaryButton>
        </FilterBar>

        {catalog.errors.length > 0 && (
          <FieldHint theme={theme} $error role="alert">
            {canAssign ? catalog.errors.join('; ') : t('agents.catalog.loadError')}
          </FieldHint>
        )}
        {!catalogLoading && <HeaderSubtitle theme={theme}>{t('agents.catalog.filterCount', { count: filteredVoices.length })}</HeaderSubtitle>}

        {/* Catalog Table */}
        <TableContainer theme={theme} style={{ maxHeight: '420px', overflowY: 'auto' }}>
          <Table>
            <TableHeader theme={theme}>
              <tr>
                {canAssign && (
                  <TableHeaderCell theme={theme} style={{ width: '150px' }}>
                    {t('agents.catalog.columns.provider')}
                  </TableHeaderCell>
                )}
                <TableHeaderCell theme={theme} style={{ width: '160px' }}>
                  {t('agents.catalog.columns.name')}
                </TableHeaderCell>
                {canAssign && (
                  <TableHeaderCell theme={theme} style={{ width: '180px' }}>
                    {t('agents.catalog.columns.voiceId')}
                  </TableHeaderCell>
                )}
                <TableHeaderCell theme={theme} style={{ width: '90px' }} $align="center">
                  {t('agents.catalog.columns.languages')}
                </TableHeaderCell>
                <TableHeaderCell theme={theme} style={{ width: '110px' }} $align="center">
                  {t('agents.catalog.columns.actions')}
                </TableHeaderCell>
              </tr>
            </TableHeader>
            <tbody>
              {filteredVoices.map((voice) => {
                const isPlaying = activeVoiceId === voice.id;
                const isLoading = loadingVoiceId === voice.id;
                const isCopied = copiedId === voice.voiceId;

                return (
                  <TableRow key={voice.id} theme={theme}>
                    {/* Provider & Model */}
                    {canAssign && (
                      <TableCell theme={theme}>
                        <ProviderTag theme={theme}>{voice.modelName}</ProviderTag>
                        <ModelSubtitle theme={theme}>{voice.modelCode}</ModelSubtitle>
                      </TableCell>
                    )}

                    {/* Name */}
                    <TableCell theme={theme}>
                      <VoiceNameWrapper theme={theme}>
                        {voice.name || t('agents.fields.unnamedVoice')}
                      </VoiceNameWrapper>
                    </TableCell>

                    {/* Voice ID with 1-click copy */}
                    {canAssign && (
                      <TableCell theme={theme}>
                        <VoiceIdPill
                          theme={theme}
                          $copied={isCopied}
                          onClick={(e) => handleCopyId(voice.voiceId, e)}
                          title={`${t('agents.catalog.copyTooltip')}: ${voice.voiceId}`}
                        >
                          {isCopied ? <HiCheck size={13} /> : <HiClipboardDocument size={13} />}
                          <span>{voice.voiceId}</span>
                        </VoiceIdPill>
                      </TableCell>
                    )}

                    {/* Languages */}
                    <TableCell theme={theme} $align="center">
                      {voice.languages.length === 0 && '—'}
                      {voice.languages.map((lang) => (
                        <LangBadge key={lang} theme={theme}>
                          {lang}
                        </LangBadge>
                      ))}
                    </TableCell>

                    {/* Audio Test Action */}
                    <TableCell theme={theme} $align="center">
                      <PlayButton
                        type="button"
                        $active={isPlaying}
                        disabled={isLoading}
                        onClick={() => handlePlayVoice(voice)}
                      >
                        {isLoading ? (
                          <>
                            <Spinner />
                            <span>{t('agents.catalog.synthesizing')}</span>
                          </>
                        ) : isPlaying ? (
                          <>
                            <SoundWave>
                              <span />
                              <span />
                              <span />
                            </SoundWave>
                            <span>{t('agents.catalog.stop')}</span>
                          </>
                        ) : (
                          <>
                            <HiPlay size={15} />
                            <span>{t('agents.catalog.play')}</span>
                          </>
                        )}
                      </PlayButton>
                    </TableCell>
                  </TableRow>
                );
              })}

              {(catalogLoading || filteredVoices.length === 0) && (
                <tr>
                  <TableCell
                    theme={theme}
                    colSpan={canAssign ? 5 : 3}
                    style={{ textAlign: 'center', padding: '32px', color: theme.colors.secondary }}
                  >
                    {t(catalogLoading ? 'agents.catalog.loading' : catalog.errors.length ? 'agents.catalog.loadError' : !catalog.hasModels ? (canAssign ? 'agents.catalog.noModels' : 'agents.catalog.clientNoVoices') : 'agents.catalog.noResults')}
                  </TableCell>
                </tr>
              )}
            </tbody>
          </Table>
        </TableContainer>
      </CatalogContainer>
    </Modal>
  );
};
