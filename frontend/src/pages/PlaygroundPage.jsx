import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import styled, { keyframes, css } from 'styled-components';
import { HiArrowLeft, HiMicrophone, HiPhone, HiPhoneXMark } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { agentsApi, playgroundSocketUrl, PLAYGROUND_SAMPLE_RATE } from 'utils/callApi';
import { describeToolCall } from 'utils/transcript';
import { createPlaygroundPlayback } from 'utils/playgroundPlayback';
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
  Badge,
  EmptyState,
  EmptyStateTitle,
  EmptyStateText,
} from 'components/ui';

// One conversation with the agent over the WS playground — the real pipeline,
// no telephony, nothing persisted (see utils/callApi.playgroundSocketUrl for
// the wire contract). Mic audio goes out as PCM16 mono @ 16 kHz; the agent's
// voice comes back the same way and is scheduled gap-free on an AudioContext
// clock; JSON text frames drive the live captions.

// 20 ms of mic audio per binary frame — what the backend expects.
const CHUNK_SAMPLES = PLAYGROUND_SAMPLE_RATE / 50;

// The capture worklet: accumulate the context's 128-sample blocks into 20 ms
// Int16 chunks and hand them to the main thread. Loaded from a Blob so the
// build needs no separate worklet asset.
const CAPTURE_WORKLET = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Int16Array(${CHUNK_SAMPLES});
    this._len = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i += 1) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this._buf[this._len] = s < 0 ? s * 0x8000 : s * 0x7fff;
      this._len += 1;
      if (this._len === this._buf.length) {
        const out = this._buf;
        this._buf = new Int16Array(out.length);
        this._len = 0;
        this.port.postMessage(out, [out.buffer]);
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCaptureProcessor);
`;

// Sub-second values keep millisecond precision; longer ones read as seconds.
const formatMs = (value, t) =>
  value < 1000
    ? `${Math.round(value)} ${t('playground.timings.ms')}`
    : `${(value / 1000).toFixed(1)} ${t('playground.timings.s')}`;

const STATUS_COLORS = {
  idle: '#6b7280',
  connecting: '#d97706',
  live: '#16a34a',
  ended: '#6b7280',
  error: '#dc2626',
};

// The pipeline's own narration ({event: "state"}, AgentStateTap on the
// backend). `pulse` marks the states where something is actively happening.
const AGENT_STATES = {
  listening: { color: '#16a34a', pulse: false },
  user_speaking: { color: '#2563eb', pulse: true },
  thinking: { color: '#d97706', pulse: true },
  speaking: { color: '#7c3aed', pulse: true },
};

// user_speaking briefly flips to listening at turn commit before thinking
// arrives — deferring "listening" by this much folds that hop into one.
const LISTENING_FLICKER_MS = 200;

// The per-turn latency report ({event: "timing"}, TurnLatencyObserver on the
// backend), one strip per turn in the transcript. Headline first, then the
// stages in the order they happen; a null field means the stage never ran
// and its chip is simply not shown. Titles carry the measurement semantics.
const TIMING_METRICS = [
  { key: 'voice_to_voice_ms', labelKey: 'vv', headline: true },
  { key: 'waiting_user_ms', labelKey: 'wait' },
  { key: 'user_turn_ms', labelKey: 'userTurn' },
  { key: 'stt_ms', labelKey: 'commit' },
  { key: 'ttt_first_token_ms', labelKey: 'llmFirst' },
  { key: 'ttt_ms', labelKey: 'llm' },
  { key: 'tts_ms', labelKey: 'tts' },
];

const Hint = styled.p`
  margin: 0 0 16px;
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
  max-width: 720px;
`;

const ToolRow = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 12px;
  margin-bottom: 16px;

  select {
    width: auto;
    min-width: 170px;
  }
`;

const statePulse = keyframes`
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.8); }
  100% { opacity: 1; transform: scale(1); }
`;

const StatePill = styled.div`
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
`;

const StateDot = styled.span`
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  background: ${({ $color }) => $color};
  ${({ $pulse }) =>
    $pulse &&
    css`
      animation: ${statePulse} 1.1s ease-in-out infinite;
    `}
`;

const LevelTrack = styled.div`
  width: 90px;
  height: 6px;
  border-radius: 3px;
  background: ${({ theme }) => theme.colors.border};
  overflow: hidden;
`;

const LevelFill = styled.div`
  height: 100%;
  border-radius: 3px;
  background: ${({ theme }) => theme.colors.accent};
  transition: width 0.1s linear;
`;

const Transcript = styled.div`
  max-width: 860px;
  min-height: 260px;
  max-height: calc(100vh - 340px);
  overflow-y: auto;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 16px;
  background: ${({ theme }) => theme.colors.background};
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const Bubble = styled.div`
  align-self: ${({ $role }) => ($role === 'assistant' ? 'flex-start' : $role === 'user' ? 'flex-end' : 'center')};
  max-width: 80%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
  opacity: ${({ $final }) => ($final ? 1 : 0.6)};
  color: ${({ $role, theme }) => ($role === 'tool' ? theme.colors.accentNeon : theme.colors.primary)};
  background: ${({ $role, theme }) =>
    $role === 'assistant'
      ? theme.colors.hover
      : $role === 'tool'
        ? `${theme.colors.accentNeon}18`
        : `${theme.colors.accent}22`};
`;

const BubbleRole = styled.div`
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: ${({ theme }) => theme.colors.muted};
  margin-bottom: 2px;
`;

const TranscriptEmpty = styled.div`
  margin: auto;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.muted};
`;

// One turn's latency numbers, as a quiet strip under the reply it measures.
const TimingRow = styled.div`
  align-self: center;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: baseline;
  gap: 3px 12px;
  max-width: 95%;
  font-size: 11px;
  color: ${({ theme }) => theme.colors.muted};
`;

const TimingChip = styled.span`
  white-space: nowrap;
  cursor: help;
  color: ${({ $headline, $alert, theme }) =>
    $alert ? '#dc2626' : $headline ? theme.colors.primary : theme.colors.muted};
  font-weight: ${({ $headline }) => ($headline ? 600 : 400)};

  code {
    font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
    font-size: 11px;
  }
`;

// A barge-in, marked where it happened in the conversation.
const Marker = styled.div`
  align-self: center;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 90%;
  font-size: 11px;
  font-style: italic;
  color: ${({ theme }) => theme.colors.muted};

  &::before,
  &::after {
    content: '';
    width: 28px;
    border-top: 1px dashed ${({ theme }) => theme.colors.border};
  }
`;

export const PlaygroundPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const { agentId } = useParams();
  const navigate = useNavigate();

  const [agent, setAgent] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [language, setLanguage] = useState('');
  const [status, setStatus] = useState('idle'); // idle|connecting|live|ended|error
  const [errorText, setErrorText] = useState(null);
  const [muted, setMuted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [micLevel, setMicLevel] = useState(0);
  const [agentState, setAgentState] = useState(null);

  const wsRef = useRef(null);
  const listeningTimerRef = useRef(null);
  const audioCtxRef = useRef(null);
  const workletNodeRef = useRef(null);
  const streamRef = useRef(null);
  const playbackRef = useRef(null);
  const sessionGenerationRef = useRef(0);
  const startingRef = useRef(false);
  const mutedRef = useRef(false);
  const levelRef = useRef(0);
  const transcriptRef = useRef(null);

  useEffect(() => {
    let active = true;
    agentsApi
      .get(agentId)
      .then((data) => active && setAgent(data))
      .catch((e) => active && setLoadError(e.message));
    return () => {
      active = false;
    };
  }, [agentId]);

  // The captions follow the conversation — keep the newest line in view.
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // The mic meter reads a ref on a slow clock so 50 chunks/s never become 50
  // renders/s.
  useEffect(() => {
    const timer = setInterval(() => {
      setMicLevel((prev) => {
        const next = Math.round(Math.min(1, levelRef.current * 3) * 100);
        return next === prev ? prev : next;
      });
    }, 120);
    return () => clearInterval(timer);
  }, []);

  const stopPlayback = useCallback(() => {
    playbackRef.current?.clear();
  }, []);

  const teardown = useCallback(({ drainPlayback = false } = {}) => {
    sessionGenerationRef.current += 1;
    startingRef.current = false;
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      if (ws.readyState <= WebSocket.OPEN) ws.close();
    }
    const worklet = workletNodeRef.current;
    if (worklet) {
      worklet.port.onmessage = null;
      worklet.disconnect();
    }
    workletNodeRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (drainPlayback) playbackRef.current?.finish();
    else {
      playbackRef.current?.dispose();
      playbackRef.current = null;
    }
    audioCtxRef.current = null;
    levelRef.current = 0;
    if (listeningTimerRef.current) {
      clearTimeout(listeningTimerRef.current);
      listeningTimerRef.current = null;
    }
    setAgentState(null);
  }, []);

  useEffect(() => teardown, [teardown]);

  const playChunk = useCallback((arrayBuffer) => {
    playbackRef.current?.play(arrayBuffer);
  }, []);

  // States arrive only on change. The one hop worth smoothing over is the
  // backend's own hint: user_speaking flips to listening at turn commit right
  // before thinking arrives — so "listening" is applied on a short fuse that
  // any other state cancels.
  const applyAgentState = useCallback((state) => {
    if (listeningTimerRef.current) {
      clearTimeout(listeningTimerRef.current);
      listeningTimerRef.current = null;
    }
    if (state === 'listening') {
      listeningTimerRef.current = setTimeout(() => {
        listeningTimerRef.current = null;
        setAgentState('listening');
      }, LISTENING_FLICKER_MS);
      return;
    }
    setAgentState(state);
  }, []);

  // A barge-in leaves a mark where it happened; it also seals any open
  // assistant bubble, so what follows starts a fresh one.
  const applyInterruption = useCallback((cutShort) => {
    setMessages((prev) => [...prev, { role: 'marker', kind: 'interruption', while: cutShort }]);
  }, []);

  // VOAD-58: a completed tool call (send_sms, end_call, ...), rendered as a
  // friendly line instead of raw JSON — see utils/transcript.
  const applyToolCall = useCallback(
    (event) => {
      setMessages((prev) => [
        ...prev,
        { role: 'tool', text: describeToolCall(t, event.name, event.arguments) },
      ]);
    },
    [t]
  );

  // One latency strip per turn. A report where no stage ran (all fields null)
  // would render an empty row, so it is dropped here.
  const applyTiming = useCallback((event) => {
    if (!TIMING_METRICS.some(({ key }) => event[key] != null)) return;
    setMessages((prev) => [...prev, { role: 'timing', data: event }]);
  }, []);

  const applyTranscript = useCallback((event) => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (event.role === 'user') {
        // Interim frames rewrite the open user line; the final frame seals it.
        if (last && last.role === 'user' && !last.final) {
          next[next.length - 1] = { role: 'user', text: event.text, final: Boolean(event.final) };
        } else {
          next.push({ role: 'user', text: event.text, final: Boolean(event.final) });
        }
      } else {
        // The agent's reply arrives one TTS chunk at a time — consecutive
        // chunks belong to the same bubble.
        if (last && last.role === 'assistant') {
          next[next.length - 1] = { ...last, text: `${last.text} ${event.text}`.trim() };
        } else {
          next.push({ role: 'assistant', text: event.text, final: true });
        }
      }
      return next;
    });
  }, []);

  const start = async () => {
    if (!agent || wsRef.current || startingRef.current) return;
    teardown();
    const generation = sessionGenerationRef.current;
    startingRef.current = true;
    setErrorText(null);
    setMessages([]);
    setStatus('connecting');

    if (!navigator.mediaDevices?.getUserMedia) {
      startingRef.current = false;
      setStatus('error');
      setErrorText(t('playground.micUnsupported'));
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: PLAYGROUND_SAMPLE_RATE,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (_) {
      if (sessionGenerationRef.current !== generation) return;
      startingRef.current = false;
      setStatus('error');
      setErrorText(t('playground.micDenied'));
      return;
    }
    if (sessionGenerationRef.current !== generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;

    // An authenticated round trip right before the handshake: WebSocket cannot
    // follow the fetch wrapper's refresh-and-retry, so make sure the access
    // token cookie is fresh while we still can.
    try {
      await agentsApi.get(agent.id);
    } catch (_) {
      /* the socket will report auth trouble on its own */
    }
    if (sessionGenerationRef.current !== generation) return;

    try {
      // One context both ways, at the wire rate: mic audio is never resampled
      // twice, and received chunks can be wrapped in AudioBuffers verbatim.
      const ctx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: PLAYGROUND_SAMPLE_RATE,
      });
      audioCtxRef.current = ctx;
      playbackRef.current = createPlaygroundPlayback(ctx, PLAYGROUND_SAMPLE_RATE);

      const workletUrl = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'text/javascript' }));
      try {
        await ctx.audioWorklet.addModule(workletUrl);
      } finally {
        URL.revokeObjectURL(workletUrl);
      }
      if (audioCtxRef.current !== ctx) return; // torn down while loading

      const ws = new WebSocket(playgroundSocketUrl(agent.id, language || undefined));
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
      startingRef.current = false;
      // onclose fires with stale render state, so "did the handshake ever
      // succeed" lives on the socket itself.
      let opened = false;

      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, 'pcm-capture');
      workletNodeRef.current = node;
      source.connect(node);

      node.port.onmessage = (e) => {
        if (wsRef.current !== ws) return;
        const chunk = e.data; // Int16Array, CHUNK_SAMPLES long
        // Muted keeps the stream ticking with silence: VAD and the silence
        // policy run off frames arriving, not off frames existing.
        if (mutedRef.current) chunk.fill(0);
        let sum = 0;
        for (let i = 0; i < chunk.length; i += 1) sum += (chunk[i] / 0x8000) ** 2;
        levelRef.current = Math.sqrt(sum / chunk.length);
        if (ws.readyState === WebSocket.OPEN) ws.send(chunk.buffer);
      };

      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        opened = true;
        setStatus('live');
        ctx.resume().catch(() => undefined);
      };

      ws.onmessage = (e) => {
        if (wsRef.current !== ws) return;
        if (typeof e.data !== 'string') {
          playChunk(e.data);
          return;
        }
        let event;
        try {
          event = JSON.parse(e.data);
        } catch (_) {
          return;
        }
        if (event.event === 'transcript') applyTranscript(event);
        else if (event.event === 'state') applyAgentState(event.state);
        // Barge-in: named right before the user_speaking state that follows it.
        else if (event.event === 'interruption') applyInterruption(event.while);
        // Per-turn latency report, arriving after the agent finishes the turn.
        else if (event.event === 'timing') applyTiming(event);
        else if (event.event === 'tool_call') applyToolCall(event);
        // Barge-in playback: the caller spoke over the agent — drop buffered audio now.
        else if (event.event === 'clear') stopPlayback();
        else if (event.event === 'stop') {
          teardown({ drainPlayback: true });
          setStatus('ended');
        }
      };

      ws.onclose = (e) => {
        if (wsRef.current !== ws) return;
        teardown({ drainPlayback: opened });
        if (e.code === 4404) {
          setStatus('error');
          setErrorText(t('playground.unknownAgent'));
        } else if (e.code === 4500) {
          setStatus('error');
          setErrorText(t('playground.badConfig'));
        } else if (!opened) {
          setStatus('error');
          setErrorText(t('playground.connectionFailed'));
        } else {
          setStatus('ended');
        }
      };
    } catch (_) {
      if (sessionGenerationRef.current !== generation) return;
      teardown();
      setStatus('error');
      setErrorText(t('playground.startFailed'));
    }
  };

  const stop = () => {
    teardown();
    setStatus('ended');
  };

  const toggleMute = () => {
    mutedRef.current = !mutedRef.current;
    setMuted(mutedRef.current);
  };

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

  const live = status === 'live' || status === 'connecting';

  return (
    <PageContent>
      <HeaderSection theme={theme}>
        <HeaderActions>
          <SecondaryButton theme={theme} type="button" onClick={() => navigate(`/agents/${agent.id}`)}>
            <HiArrowLeft size={15} /> {t('playground.back')}
          </SecondaryButton>
          <PageTitle theme={theme}>
            {agent.name} — {t('playground.title')}
          </PageTitle>
          <Badge $color={STATUS_COLORS[status]}>{t(`playground.${status}`)}</Badge>
        </HeaderActions>
      </HeaderSection>

      <ContentScroll theme={theme}>
        <Hint theme={theme}>{t('playground.hint')}</Hint>

        <ToolRow>
          <Select
            theme={theme}
            value={language}
            disabled={live}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value="">
              {t('playground.defaultOption', { language: agent.default_language })}
            </option>
            {agent.languages.map((row) => (
              <option key={row.id} value={row.language}>
                {row.language}
              </option>
            ))}
          </Select>

          {live ? (
            <DangerButton theme={theme} type="button" onClick={stop}>
              <HiPhoneXMark size={15} /> {t('playground.stop')}
            </DangerButton>
          ) : (
            <PrimaryButton theme={theme} type="button" onClick={start}>
              <HiPhone size={15} /> {t('playground.start')}
            </PrimaryButton>
          )}

          {live && agentState && (
            <StatePill theme={theme}>
              <StateDot
                $color={AGENT_STATES[agentState]?.color ?? '#6b7280'}
                $pulse={Boolean(AGENT_STATES[agentState]?.pulse)}
              />
              {AGENT_STATES[agentState] ? t(`playground.states.${agentState}`) : agentState}
            </StatePill>
          )}

          {live && (
            <>
              <SecondaryButton
                theme={theme}
                type="button"
                onClick={toggleMute}
                title={t(muted ? 'playground.unmute' : 'playground.mute')}
              >
                <HiMicrophone size={15} style={{ opacity: muted ? 0.35 : 1 }} />
                {muted ? t('playground.muted') : ''}
              </SecondaryButton>
              <LevelTrack theme={theme}>
                <LevelFill theme={theme} style={{ width: `${muted ? 0 : micLevel}%` }} />
              </LevelTrack>
            </>
          )}
        </ToolRow>

        {errorText && (
          <Hint theme={theme} style={{ color: '#dc2626' }}>
            {errorText}
          </Hint>
        )}

        <Transcript theme={theme} ref={transcriptRef}>
          {messages.length === 0 ? (
            <TranscriptEmpty theme={theme}>{t('playground.transcriptEmpty')}</TranscriptEmpty>
          ) : (
            messages.map((msg, i) =>
              msg.role === 'marker' ? (
                <Marker key={i} theme={theme}>
                  {t(`playground.interrupted.${msg.while}`)}
                </Marker>
              ) : msg.role === 'timing' ? (
                <TimingRow key={i} theme={theme}>
                  {msg.data.turn != null && <TimingChip theme={theme}>#{msg.data.turn}</TimingChip>}
                  {TIMING_METRICS.filter(({ key }) => msg.data[key] != null).map(
                    ({ key, labelKey, headline }) => (
                      <TimingChip
                        key={key}
                        theme={theme}
                        $headline={headline}
                        title={t(`playground.timings.titles.${labelKey}`)}
                      >
                        {t(`playground.timings.${labelKey}`)} <code>{formatMs(msg.data[key], t)}</code>
                      </TimingChip>
                    )
                  )}
                  {msg.data.interrupted && (
                    <TimingChip theme={theme} $alert title={t('playground.timings.titles.interrupted')}>
                      {t('playground.timings.interruptedFlag')}
                    </TimingChip>
                  )}
                </TimingRow>
              ) : (
                <Bubble key={i} theme={theme} $role={msg.role} $final={msg.final}>
                  <BubbleRole theme={theme}>
                    {msg.role === 'tool'
                      ? t('calls.roles.tool')
                      : t(msg.role === 'assistant' ? 'playground.agent' : 'playground.you')}
                  </BubbleRole>
                  {msg.text}
                </Bubble>
              )
            )
          )}
        </Transcript>
      </ContentScroll>
    </PageContent>
  );
};
