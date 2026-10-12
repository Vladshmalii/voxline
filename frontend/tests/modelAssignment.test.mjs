import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, fields, form, permissions, ThemeProvider, I18nProvider;
before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom', ssr: { noExternal: ['styled-components'] } });
  fields = await server.ssrLoadModule('/src/pages/agentFields.js');
  form = await server.ssrLoadModule('/src/components/ResourceForm.jsx');
  permissions = await server.ssrLoadModule('/src/utils/permissions.js');
  ({ ThemeProvider } = await server.ssrLoadModule('/src/contexts/ThemeContext.jsx'));
  ({ I18nProvider } = await server.ssrLoadModule('/src/contexts/I18nContext.jsx'));
});
after(async () => { await server?.close(); });

const assigned = { stt_model_id: 1, tts_model_id: 2, ttt_model_id: 3, ttt_extra_body: { model: 'secret' } };
const models = ['stt', 'tts', 'ttt'].map((kind, i) => ({ id: i + 1, kind, name: kind, is_active: true }));
for (const role of ['owner', 'staff', 'viewer', 'none', undefined]) {
  test(`${role}: model selectors and their payload values are absent`, () => {
    const specs = fields.modelFields(models, {}, {}, permissions.canAssignModels(role));
    const names = specs.map((field) => field.name);
    for (const name of Object.keys(assigned)) assert.equal(names.includes(name), false);
    assert.ok(names.includes('tts_voice'));
    const values = form.buildInitialValues(specs, { ...assigned, tts_voice: 'vivian' });
    // Even stale/injected form values cannot slip into the API payload.
    const { payload, errors } = form.buildPayload(specs, { ...values, ...assigned });
    assert.deepEqual(errors, {});
    for (const name of Object.keys(assigned)) assert.equal(Object.hasOwn(payload, name), false);
    assert.equal(payload.tts_voice, 'vivian');
    assert.equal(permissions.canView('models', role), false);
    assert.equal(permissions.canWrite('providers', role), false);
  });
}

function renderVoiceField(spec, values) {
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  try {
    return renderToStaticMarkup(createElement(ThemeProvider, null,
      createElement(I18nProvider, null,
        createElement(form.ResourceForm, { fields: [{ ...spec, helpKey: undefined }], values, errors: {}, onChange: () => {} }))));
  } finally {
    if (previousStorage === undefined) delete globalThis.localStorage;
    else Object.defineProperty(globalThis, 'localStorage', previousStorage);
  }
}

test('client chooses duplicate names by language without a raw ID text input', () => {
  const voices = { options: [
    { id: 'private-ru', name: 'Anna', language: 'ru' },
    { id: 'private-en', name: 'Anna', language: 'en' },
  ] };
  const spec = fields.modelFields(models, voices, {}, false).find((field) => field.name === 'tts_voice');
  const values = { tts_voice: 'private-ru' };
  const html = renderVoiceField(spec, values);
  assert.doesNotMatch(html, /<input/);
  assert.match(html, />Anna \(en\)<\/option>/);
  assert.match(html, /value="private-ru" selected="">Anna \(ru\)<\/option>/);
  assert.doesNotMatch(html.replace(/<[^>]+>/g, ''), /private-ru|private-en/);
  assert.equal(form.buildPayload([spec], values).payload.tts_voice, 'private-ru');
  const filtered = renderVoiceField(spec, { ...values, tts_voice__lang: 'en' });
  assert.match(filtered, /value="private-ru" selected="">Anna \(ru\)<\/option>/);
});

test('catalogue failure preserves the saved client voice without exposing its ID', () => {
  const spec = fields.modelFields(models, {}, {}, false).find((field) => field.name === 'tts_voice');
  const values = { tts_voice: 'unlisted-private-id' };
  const html = renderVoiceField(spec, values);
  assert.doesNotMatch(html, /<input/);
  assert.match(html, /value="unlisted-private-id" selected=""/);
  assert.doesNotMatch(html.replace(/<[^>]+>/g, ''), /unlisted-private-id/);
  assert.equal(form.buildPayload([spec], values).payload.tts_voice, 'unlisted-private-id');
});

test('admin keeps the custom voice ID input', () => {
  const spec = fields.modelFields(models, {}, {}, true).find((field) => field.name === 'tts_voice');
  assert.match(renderVoiceField(spec, { tts_voice: 'custom-admin-id' }), /<input[^>]+value="custom-admin-id"/);
});
for (const role of ['admin', 'super_admin']) {
  test(`${role}: can select all three models`, () => {
    const specs = fields.modelFields(models, {}, {}, permissions.canAssignModels(role));
    const values = form.buildInitialValues(specs, { ...assigned, tts_voice: 'vivian' });
    const { payload, errors } = form.buildPayload(specs, values);
    assert.deepEqual(errors, {});
    // ttt_extra_body lives in the org-wide admin settings form, not in these model fields.
    for (const [key, value] of Object.entries(assigned)) {
      if (key !== 'ttt_extra_body') assert.deepEqual(payload[key], value);
    }
    assert.equal(permissions.canView('models', role), true);
  });
}
test('client can still manage agents and preview their voice', () => {
  assert.equal(permissions.canManageAgents('owner'), true);
  assert.equal(permissions.canPreviewVoice('owner'), true);
  assert.equal(permissions.canPreviewVoice('staff'), true);
});

for (const role of ['owner', 'staff', 'viewer', undefined, 'admin', 'super_admin']) {
  test(`${role}: route fields follow admin permissions without clearing existing assignments`, () => {
    const canAssign = permissions.canAssignModels(role);
    const routes = [{ id: 7, name: 'Internal route', adapter: 'sip_bridge', is_active: true }];
    const specs = [...fields.basicFields(), ...fields.smsToolFields(routes, canAssign)];
    const saved = { name: 'Agent', messaging_id: 7, sms_tool_enabled: true, sms_tool_message: 'Hello' };
    const values = form.buildInitialValues(specs, saved);
    const { payload, errors } = form.buildPayload(specs, { ...values, messaging_id: 7 });
    assert.deepEqual(errors, {});
    // The trunk is organization-wide (admin settings), never an agent field.
    assert.equal(specs.some((field) => field.name === 'telephony_id'), false);
    assert.equal(Object.hasOwn(payload, 'telephony_id'), false);
    assert.equal(specs.some((field) => field.name === 'messaging_id'), canAssign);
    assert.equal(Object.hasOwn(payload, 'messaging_id'), canAssign);
    if (canAssign) assert.equal(payload.messaging_id, 7);
    assert.equal(payload.sms_tool_enabled, true);
    assert.equal(payload.sms_tool_message, 'Hello');
  });
}
test('telephony is picked in the organization-wide admin settings', () => {
  const routes = [{ id: 7, name: 'Internal route', adapter: 'sip_bridge', is_active: true }];
  const telephony = fields.adminFields(routes).find((field) => field.name === 'telephony_id');
  assert.ok(telephony);
  assert.deepEqual(telephony.options, [{ value: 7, label: 'Internal route (sip_bridge)' }]);
});
