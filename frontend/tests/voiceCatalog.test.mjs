import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadVoiceCatalog, loadModelVoices, voicePreviewRequest, voiceLabelForId } from '../src/utils/voiceCatalog.js';

const model = (id, extra = {}) => ({ id, name: `TTS ${id}`, kind: 'tts', adapter: 'cartesia', code: 'sonic-3', is_active: true, ...extra });

test('client loads every live voice from the assigned default, including custom voices', async () => {
  const liveVoices = Array.from({ length: 250 }, (_, i) => ({ id: `custom-${i}`, name: `Voice ${i}`, language: i % 2 ? 'ru' : 'en' }));
  const api = {
    defaults: async () => ({ tts_model_id: 42 }),
    get: async (id) => { assert.equal(id, 42); return model(id); },
    list: async () => { throw new Error('Clients must not enumerate models'); },
    voices: async (id) => { assert.equal(id, 42); return liveVoices; },
  };
  const catalog = await loadVoiceCatalog(api, false);
  assert.equal(catalog.voices.length, 250);
  assert.deepEqual(catalog.errors, []);
  assert.ok(catalog.voices.every((voice) => voice.modelId === 42));
  const voice = catalog.voices.find((voice) => voice.voiceId === 'custom-249');
  assert.deepEqual(voicePreviewRequest(voice, 'Привет!', false), { voice: 'custom-249', text: 'Привет!', language: 'ru' });
});

test('preview uses the exact model that listed a voice, even with the same adapter', async () => {
  const catalog = await loadVoiceCatalog({
    list: async () => [model(1), model(2)],
    voices: async () => [{ id: 'shared', name: 'Shared voice', language: null }],
  }, true);
  assert.equal(new Set(catalog.voices.map((voice) => voice.id)).size, 2);
  const voice = catalog.voices.find((voice) => voice.modelId === 2);
  const request = voicePreviewRequest(voice, 'Hello', true);
  assert.equal(request.modelId, 2);
  assert.equal(request.voice, 'shared');
  assert.equal(request.language, undefined);
});

test('live catalogue failure is visible and never replaced with hardcoded Cartesia presets', async () => {
  const catalog = await loadVoiceCatalog({
    list: async () => [model(1), model(2, { adapter: 'openrouter' })],
    voices: async (id) => {
      if (id === 1) throw new Error('Authentication failed');
      return [{ id: 'live-only', name: 'Live' }];
    },
  }, true);
  assert.deepEqual(catalog.voices.map((voice) => voice.voiceId), ['live-only']);
  assert.deepEqual(catalog.errors, ['TTS 1: Authentication failed']);
});

test('an empty live catalogue stays empty rather than inventing available voices', async () => {
  const catalog = await loadVoiceCatalog({ list: async () => [model(1)], voices: async () => [] }, true);
  assert.deepEqual(catalog, { voices: [], errors: [], hasModels: true });
});

test('no assigned default does not fall back to another model', async () => {
  const catalog = await loadVoiceCatalog({ defaults: async () => ({ tts_model_id: null }) }, false);
  assert.deepEqual(catalog, { voices: [], errors: [], hasModels: false });
});

test('fixed voices remain available only for adapters without a live catalogue', async () => {
  const catalog = await loadVoiceCatalog({ list: async () => [model(3, { adapter: 'qwen3_tts' })] }, true);
  assert.ok(catalog.voices.length > 0);
  assert.ok(catalog.voices.every((voice) => voice.modelId === 3 && voice.adapter === 'qwen3_tts'));
  assert.deepEqual(catalog.errors, []);
});

test('admin model enumeration loads every page and ignores inactive models', async () => {
  const calls = [];
  const catalog = await loadVoiceCatalog({
    list: async (query) => {
      calls.push(query);
      return query.offset === 0
        ? Array.from({ length: 500 }, (_, i) => model(i, { is_active: false }))
        : [model(501)];
    },
    voices: async (id) => { assert.equal(id, 501); return [{ id: 'last', name: 'Last page' }]; },
  }, true);
  assert.deepEqual(calls.map((call) => call.offset), [0, 500]);
  assert.ok(calls.every((call) => call.kind === 'tts' && call.is_active === true));
  assert.deepEqual(catalog.voices.map((voice) => voice.voiceId), ['last']);
});

test('equal voice names remain distinct by language and keep the correct preview ID', async () => {
  const voices = [
    { id: 'anna-ru-id', name: 'Anna', language: 'ru' },
    { id: 'anna-en-id', name: 'Anna', language: 'en' },
  ];
  const catalog = await loadVoiceCatalog({
    defaults: async () => ({ tts_model_id: 1 }),
    get: async () => model(1),
    voices: async () => voices,
  }, false);
  assert.deepEqual(catalog.voices.map((voice) => voice.languages), [['en'], ['ru']]);
  assert.equal(voiceLabelForId(voices, 'anna-ru-id', 'Current'), 'Anna (ru)');
  assert.equal(voiceLabelForId(voices, 'anna-en-id', 'Current'), 'Anna (en)');
  assert.deepEqual(voicePreviewRequest(catalog.voices[0], 'Hello', false), {
    voice: 'anna-en-id', language: 'en', text: 'Hello',
  });
});

test('a missing or unnamed voice never falls back to a technical ID in client labels', () => {
  assert.equal(voiceLabelForId([], 'private-id', 'Current voice', 'ru'), 'Current voice (ru)');
  assert.equal(voiceLabelForId([{ id: 'private-id', name: '', language: 'en' }], 'private-id', 'Unnamed'), 'Unnamed (en)');
});

test('fixed voices are available in agent pickers with names and all languages', async () => {
  const voices = await loadModelVoices({ get: async () => model(1, { adapter: 'qwen3_tts' }) }, 1);
  assert.equal(voiceLabelForId(voices, 'vivian', 'Current'), 'Vivian (ru, en, zh)');
});

test('model voices are fetched once and shared between id and model-object callers', async () => {
  let getCalls = 0;
  let voiceCalls = 0;
  const api = {
    get: async () => { getCalls += 1; return model(6); },
    voices: async () => { voiceCalls += 1; return [{ id: 'v', name: 'V' }]; },
  };
  const [byId, again] = await Promise.all([loadModelVoices(api, 6), loadModelVoices(api, 6)]);
  const byModel = await loadModelVoices(api, model(6));
  assert.equal(byId, again);
  assert.equal(byId, byModel);
  assert.equal(getCalls, 1);
  assert.equal(voiceCalls, 1);
});

test('a failed voice fetch is not cached and force bypasses a settled entry', async () => {
  let calls = 0;
  const api = {
    get: async () => model(6),
    voices: async () => {
      calls += 1;
      if (calls === 1) throw new Error('boom');
      return [{ id: `call-${calls}`, name: 'V' }];
    },
  };
  await assert.rejects(loadModelVoices(api, 6), /boom/);
  assert.equal((await loadModelVoices(api, 6))[0].id, 'call-2');
  assert.equal((await loadModelVoices(api, 6))[0].id, 'call-2');
  assert.equal((await loadModelVoices(api, 6, { force: true }))[0].id, 'call-3');
});

test('the catalogue is cached, but a partial one (with errors) is retried next time', async () => {
  let listCalls = 0;
  let failing = true;
  const api = {
    list: async () => { listCalls += 1; return [model(1), model(2)]; },
    voices: async (id) => {
      if (id === 1 && failing) throw new Error('down');
      return [{ id: `v${id}`, name: `V${id}` }];
    },
  };
  const partial = await loadVoiceCatalog(api, true);
  assert.equal(partial.errors.length, 1);
  failing = false;
  const full = await loadVoiceCatalog(api, true);
  assert.deepEqual(full.errors, []);
  assert.equal(full.voices.length, 2);
  assert.equal(await loadVoiceCatalog(api, true), full);
  assert.equal(listCalls, 2);
});
