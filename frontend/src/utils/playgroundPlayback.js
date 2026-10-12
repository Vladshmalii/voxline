// A browser owns a small audio queue even after the server has sent its last
// chunk. Server hangup drains that queue; barge-in and local hangup discard it.
export const createPlaygroundPlayback = (context, sampleRate) => {
  const sources = new Set();
  let nextPlayTime = 0;
  let finishing = false;
  let closed = false;
  let closeTimer = null;

  const clear = () => {
    sources.forEach((source) => {
      source.onended = null;
      try {
        source.stop();
      } catch (_) {
        /* already ended */
      }
      source.disconnect();
    });
    sources.clear();
    nextPlayTime = 0;
  };

  const dispose = () => {
    if (closed) return;
    closed = true;
    clearTimeout(closeTimer);
    context.removeEventListener('statechange', onStateChange);
    clear();
    if (context.state !== 'closed') context.close().catch(() => undefined);
  };

  const closeAfterOutput = () => {
    if (closed || closeTimer !== null) return;
    // onended means rendered, not necessarily heard through the output device.
    const tailSeconds = (context.baseLatency || 0) + (context.outputLatency || 0) + 0.04;
    closeTimer = setTimeout(dispose, tailSeconds * 1000);
  };

  const onStateChange = () => {
    // Suspended audio cannot drain. Do not retain a session indefinitely when
    // the browser or OS suspends its audio context during shutdown.
    if (finishing && context.state !== 'running') dispose();
  };

  return {
    play(arrayBuffer) {
      if (finishing || closed) return;
      const int16 = new Int16Array(arrayBuffer);
      if (!int16.length) return;
      const buffer = context.createBuffer(1, int16.length, sampleRate);
      const samples = buffer.getChannelData(0);
      for (let i = 0; i < int16.length; i += 1) samples[i] = int16[i] / 0x8000;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      const startAt = Math.max(context.currentTime + 0.04, nextPlayTime);
      nextPlayTime = startAt + buffer.duration;
      sources.add(source);
      source.onended = () => {
        sources.delete(source);
        source.disconnect();
        if (finishing && !sources.size) closeAfterOutput();
      };
      source.start(startAt);
    },
    clear,
    dispose,
    finish() {
      if (finishing || closed) return;
      finishing = true;
      context.addEventListener('statechange', onStateChange);
      if (context.state !== 'running') dispose();
      else if (!sources.size) closeAfterOutput();
    },
  };
};
