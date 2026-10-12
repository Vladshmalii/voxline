import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createPlaygroundPlayback } from '../src/utils/playgroundPlayback.js';

const fakeContext = () => {
  const listeners = new Set();
  return {
    state: 'running', currentTime: 1, baseLatency: 0.04, outputLatency: 0.06,
    destination: {}, sources: [], closed: 0,
    addEventListener(type, listener) { listeners.add(listener); },
    removeEventListener(type, listener) { listeners.delete(listener); },
    setState(state) {
      this.state = state;
      [...listeners].forEach((listener) => listener());
    },
    close() {
      this.closed += 1;
      this.setState('closed');
      return Promise.resolve();
    },
    createBuffer(channels, length, rate) {
      const samples = new Float32Array(length);
      return { duration: length / rate, getChannelData: () => samples };
    },
    createBufferSource() {
      const source = {
        stopped: 0, disconnected: 0, onended: null,
        connect() {},
        disconnect() { this.disconnected += 1; },
        start(at) { this.startedAt = at; },
        stop() { this.stopped += 1; this.onended?.(); },
        end() { this.onended?.(); },
      };
      this.sources.push(source);
      return source;
    },
  };
};

const chunk = () => new Int16Array([0, 16384, -32768, 32767]).buffer;

test('server hangup preserves every queued chunk until playback and output latency finish', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const context = fakeContext();
  const playback = createPlaygroundPlayback(context, 16000);
  playback.play(chunk());
  playback.play(chunk());
  playback.finish();
  playback.finish(); // stop followed by WebSocket close is harmless.
  playback.play(chunk()); // No new audio once the session is ending.
  assert.equal(context.sources.length, 2);
  assert.equal(context.sources[0].stopped, 0);
  assert.equal(context.sources[1].stopped, 0);
  t.mock.timers.tick(10000);
  assert.equal(context.closed, 0); // Wait for actual playback, not a wall clock estimate.
  context.sources[0].end();
  assert.equal(context.closed, 0);
  context.sources[1].end();
  t.mock.timers.tick(139);
  assert.equal(context.closed, 0);
  t.mock.timers.tick(1);
  assert.equal(context.closed, 1);
});

test('PCM conversion and contiguous scheduling are preserved', () => {
  const context = fakeContext();
  const playback = createPlaygroundPlayback(context, 16000);
  playback.play(chunk());
  playback.play(chunk());
  assert.deepEqual([...context.sources[0].buffer.getChannelData(0)], [0, 0.5, -1, 32767 / 32768]);
  assert.equal(context.sources[0].startedAt, 1.04);
  assert.equal(context.sources[1].startedAt, 1.04 + 4 / 16000);
  playback.dispose();
});

test('barge-in immediately clears playback but permits the next response', () => {
  const context = fakeContext();
  const playback = createPlaygroundPlayback(context, 16000);
  playback.play(chunk());
  playback.clear();
  assert.equal(context.sources[0].stopped, 1);
  assert.equal(context.sources[0].disconnected, 1);
  assert.equal(context.closed, 0);
  context.currentTime = 2;
  playback.play(chunk());
  assert.equal(context.sources[1].startedAt, 2.04);
  playback.dispose();
});

test('local hangup or navigation stops a draining farewell immediately and only once', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const context = fakeContext();
  const playback = createPlaygroundPlayback(context, 16000);
  playback.play(chunk());
  playback.finish();
  playback.dispose();
  playback.dispose();
  t.mock.timers.tick(1000);
  assert.equal(context.sources[0].stopped, 1);
  assert.equal(context.closed, 1);
});

test('late completion of old playback cannot close a new conversation', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const oldContext = fakeContext();
  const oldPlayback = createPlaygroundPlayback(oldContext, 16000);
  oldPlayback.play(chunk());
  const lateEnded = oldContext.sources[0].onended;
  oldPlayback.finish();
  oldPlayback.dispose();
  const newContext = fakeContext();
  const newPlayback = createPlaygroundPlayback(newContext, 16000);
  newPlayback.play(chunk());
  lateEnded();
  t.mock.timers.tick(1000);
  assert.equal(oldContext.closed, 1);
  assert.equal(newContext.closed, 0);
  assert.equal(newContext.sources[0].stopped, 0);
  newPlayback.dispose();
});

test('hangup with no queued audio closes the context', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const context = fakeContext();
  createPlaygroundPlayback(context, 16000).finish();
  t.mock.timers.tick(140);
  assert.equal(context.closed, 1);
});

test('a suspended context cannot leave a draining conversation alive', () => {
  const context = fakeContext();
  const playback = createPlaygroundPlayback(context, 16000);
  playback.play(chunk());
  playback.finish();
  context.setState('suspended');
  assert.equal(context.sources[0].stopped, 1);
  assert.equal(context.closed, 1);
});
