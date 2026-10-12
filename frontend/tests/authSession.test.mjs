import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  isRefreshable401,
  isSessionPath,
  safeNextPath,
  buildLoginPath,
  isApiUrl,
  normalizeMe,
  formatApiError,
} from '../src/utils/authSession.js';

test('only token_expired is refreshable', () => {
  assert.equal(isRefreshable401('token_expired'), true);
  for (const d of ['unauthorized', 'token_invalid', null, undefined, '']) assert.equal(isRefreshable401(d), false);
});

test('session endpoints are recognised', () => {
  assert.equal(isSessionPath('/api/v1/auth/login'), true);
  assert.equal(isSessionPath('http://h:1/api/v1/auth/refresh?x=1'), true);
  assert.equal(isSessionPath('/api/v1/auth/logout'), true);
  assert.equal(isSessionPath('/api/v1/auth/me'), false);
  assert.equal(isSessionPath('/api/v1/auth/login_history'), false);
});

test('safeNextPath only lets same-app paths through', () => {
  assert.equal(safeNextPath('/calls?page=2#x'), '/calls?page=2#x');
  for (const bad of ['https://evil.com', '//evil.com', '/\\evil.com', 'calls', '', null, undefined, '/login', '/login?next=/a'])
    assert.equal(safeNextPath(bad), '/');
});

test('buildLoginPath keeps and encodes next', () => {
  assert.equal(buildLoginPath('/'), '/login');
  assert.equal(buildLoginPath('/calls?page=2'), '/login?next=%2Fcalls%3Fpage%3D2');
  assert.equal(buildLoginPath('https://evil.com'), '/login');
});

test('isApiUrl matches the configured base and same-origin paths', () => {
  const base = 'http://localhost:8086';
  assert.equal(isApiUrl('http://localhost:8086/api/v1/calls', base), true);
  assert.equal(isApiUrl('http://localhost:8086/api/v1/auth/refresh', base), false);
  assert.equal(isApiUrl('http://other:1/api/v1/calls', base), false);
  assert.equal(isApiUrl('http://localhost:8086/static/x.js', base), false);
  assert.equal(isApiUrl('/api/v1/calls', base), true);
  // same-origin mode (empty base): relative /api/v1 URLs only
  assert.equal(isApiUrl('/api/v1/calls', '', 'http://app.test'), true);
  assert.equal(isApiUrl('http://app.test/api/v1/calls', '', 'http://app.test'), true);
  assert.equal(isApiUrl('http://evil.test/api/v1/calls', '', 'http://app.test'), false);
  assert.equal(isApiUrl('/assets/app.js', '', 'http://app.test'), false);
});

test('normalizeMe flattens the /auth/me body', () => {
  const me = normalizeMe({
    user: { id: 1, email: 'a@b.c', name: 'A', is_superuser: false },
    organization: { uuid: 'u', name: 'Org' },
    role: 'owner',
  });
  assert.deepEqual(me, {
    id: 1, email: 'a@b.c', name: 'A', is_superuser: false,
    organization: { uuid: 'u', name: 'Org' }, account_role: 'owner',
  });
  assert.equal(normalizeMe(null), null);
});

test('formatApiError handles strings, validation lists and fallbacks', () => {
  assert.equal(formatApiError({ detail: 'nope' }, 400), 'nope');
  assert.equal(formatApiError({ detail: [{ loc: ['body', 'email'], msg: 'bad' }, { msg: 'x' }] }, 422), 'email: bad; x');
  assert.equal(formatApiError(null, 500), 'Request failed (500)');
});
