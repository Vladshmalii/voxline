import { VOICES_CATALOG } from '../data/voicesCatalog.js';

// These adapters have no voice-listing endpoint. Live catalogues must never
// silently fall back to the old presets after an authentication/network error.
const FIXED_VOICE_ADAPTERS = new Set(['qwen3_tts', 'deepgram']);

export const voiceLanguages = (voice) =>
  voice.languages || (voice.language ? [voice.language] : []);

export function formatVoiceLabel(voice, fallbackName = '') {
  const name = voice.name?.trim() || fallbackName;
  const languages = voiceLanguages(voice);
  return languages.length ? `${name} (${languages.join(', ')})` : name;
}

export function voiceLabelForId(voices, id, fallbackName, language) {
  const voice = (voices || []).find((item) => item.id === id);
  return formatVoiceLabel(voice || { language }, fallbackName);
}

// Voice listings come from the vendor and are slow, so they are cached for the
// session: the shell warms them right after sign-in (prefetchVoiceCatalog) and
// every picker/modal reuses the same in-flight or settled promise. Keyed per
// `api` object, so stubs in tests never share state. A page reload (also what
// an organization switch does) starts from an empty cache.
const VOICE_CACHE_TTL_MS = 10 * 60 * 1000;
const voiceCaches = new WeakMap();

function cachedPromise(api, bucket, key, load, { force = false, keep = () => true } = {}) {
  let buckets = voiceCaches.get(api);
  if (!buckets) voiceCaches.set(api, (buckets = new Map()));
  let entries = buckets.get(bucket);
  if (!entries) buckets.set(bucket, (entries = new Map()));

  const hit = entries.get(key);
  if (!force && hit && Date.now() - hit.at < VOICE_CACHE_TTL_MS) return hit.promise;

  const entry = { at: Date.now() };
  entry.promise = load();
  entries.set(key, entry);
  // Failures (and partial catalogues) are never kept, so the next caller retries.
  entry.promise.then(
    (value) => { if (!keep(value) && entries.get(key) === entry) entries.delete(key); },
    () => { if (entries.get(key) === entry) entries.delete(key); },
  );
  return entry.promise;
}

// Share the same catalogue between preview, agent settings and name labels.
// Fixed adapters have no listing endpoint; a live catalogue failure must not
// replace the vendor's voices with unrelated presets.
export function loadModelVoices(api, modelOrId, { force = false } = {}) {
  const id = typeof modelOrId === 'object' ? modelOrId.id : modelOrId;
  return cachedPromise(api, 'modelVoices', String(id), async () => {
    const model = typeof modelOrId === 'object' ? modelOrId : await api.get(modelOrId);
    if (FIXED_VOICE_ADAPTERS.has(model.adapter)) {
      return VOICES_CATALOG.filter((voice) => voice.adapter === model.adapter)
        .map((voice) => ({ id: voice.voiceId, name: voice.name, languages: voice.languages }));
    }
    return api.voices(model.id);
  }, { force });
}

export function loadVoiceCatalog(api, canAssign, { force = false } = {}) {
  return cachedPromise(api, 'catalog', canAssign ? 'admin' : 'client',
    () => fetchVoiceCatalog(api, canAssign, force), { force, keep: (catalog) => catalog.errors.length === 0 });
}

// Fire-and-forget warm-up; errors surface later, when a picker asks again.
export function prefetchVoiceCatalog(api, canAssign) {
  loadVoiceCatalog(api, canAssign).catch(() => {});
}

async function fetchVoiceCatalog(api, canAssign, force) {
  let models;
  if (canAssign) {
    models = [];
    const limit = 500;
    for (let offset = 0; ; offset += limit) {
      const page = await api.list({ kind: 'tts', is_active: true, limit, offset });
      models.push(...page);
      if (page.length < limit) break;
    }
  } else {
    const defaults = await api.defaults();
    models = defaults.tts_model_id ? [await api.get(defaults.tts_model_id)] : [];
  }
  models = models.filter((model) => model.kind === 'tts' && model.is_active);

  const results = await Promise.allSettled(models.map(async (model) => {
    const voices = await loadModelVoices(api, model, { force });
    return voices.map((voice) => ({
      id: `${model.id}:${voice.id}`,
      voiceId: voice.id,
      name: voice.name || '',
      languages: voiceLanguages(voice),
      modelId: model.id,
      modelName: model.name,
      modelCode: model.code,
      adapter: model.adapter,
    }));
  }));
  const voices = [];
  const errors = [];
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') voices.push(...result.value);
    else errors.push(`${models[index].name}: ${result.reason?.message || String(result.reason)}`);
  });
  voices.sort((a, b) => a.name.localeCompare(b.name)
    || a.languages.join(',').localeCompare(b.languages.join(',')) || a.modelId - b.modelId);
  return { voices, errors, hasModels: models.length > 0 };
}

export function voicePreviewRequest(voice, text, canAssign) {
  return {
    voice: voice.voiceId,
    ...(canAssign ? { modelId: voice.modelId } : {}),
    text,
    language: voice.languages.includes('ru') ? 'ru' : voice.languages[0],
  };
}
