import { useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';

// Standalone <audio>-backed player for one call attempt's recording (VOAD-37).
// Play/pause, a seek scrubber, elapsed/total time and a volume slider — a
// plain HTML5 <audio> element is all this needs, no third-party audio lib.
//
// Deliberately does NOT try to sync a transcript highlight to playback time —
// that's an explicit future iteration, not this one (see CallsPage.jsx's
// AttemptDetail, which renders the transcript as a separate, independent list).

const Root = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 10px;
  background: ${({ theme }) => theme.colors.surface};
`;

const PlayButton = styled.button`
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  font-size: 13px;
  color: #fff;
  background: ${({ theme }) => theme.colors.accent};
  border: none;
  border-radius: 999px;
  cursor: pointer;

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }
`;

const Scrubber = styled.input`
  flex: 1;
  min-width: 0;
  cursor: pointer;
  accent-color: ${({ theme }) => theme.colors.accent};
`;

const Time = styled.span`
  flex-shrink: 0;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: ${({ theme }) => theme.colors.secondary};
  white-space: nowrap;
`;

const VolumeRow = styled.div`
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
`;

const VolumeSlider = styled.input`
  width: 70px;
  cursor: pointer;
  accent-color: ${({ theme }) => theme.colors.accent};
`;

// mm:ss — good enough for a call recording's likely length; never NaN even
// before metadata has loaded.
const formatTime = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = Math.floor(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, '0')}`;
};

/**
 * @param {string} recordingUrl - direct URL to the audio file. Renders
 *   nothing if absent — callers are expected to show their own "no recording
 *   available" state instead of mounting this component in that case (see
 *   CallsPage.jsx's AttemptDetail).
 */
export const CallRecordingPlayer = ({ recordingUrl }) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volume, setVolume] = useState(1);

  // A different attempt's recording was opened — drop stale playback state
  // rather than showing the previous clip's progress against the new one.
  useEffect(() => {
    setPlaying(false);
    setDuration(0);
    setCurrentTime(0);
  }, [recordingUrl]);

  if (!recordingUrl) return null;

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => setPlaying(false));
    } else {
      audio.pause();
    }
  };

  const onSeek = (e) => {
    const audio = audioRef.current;
    const next = Number(e.target.value);
    if (audio) audio.currentTime = next;
    setCurrentTime(next);
  };

  const onVolumeChange = (e) => {
    const next = Number(e.target.value);
    setVolume(next);
    if (audioRef.current) audioRef.current.volume = next;
  };

  return (
    <Root theme={theme}>
      <audio
        ref={audioRef}
        src={recordingUrl}
        preload="metadata"
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
        onDurationChange={(e) => setDuration(e.currentTarget.duration || 0)}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime || 0)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />

      <PlayButton theme={theme} type="button" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
        {playing ? '❚❚' : '▶'}
      </PlayButton>

      <Scrubber
        theme={theme}
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        value={Math.min(currentTime, duration || 0)}
        onChange={onSeek}
        disabled={!duration}
        aria-label={t('calls.detail.recordingSeek')}
      />

      <Time theme={theme}>
        {formatTime(currentTime)} / {formatTime(duration)}
      </Time>

      <VolumeRow>
        <span aria-hidden="true">🔊</span>
        <VolumeSlider
          theme={theme}
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          onChange={onVolumeChange}
          aria-label={t('calls.detail.recordingVolume')}
        />
      </VolumeRow>
    </Root>
  );
};
