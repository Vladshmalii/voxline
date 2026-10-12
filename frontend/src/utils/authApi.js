import { fetchWithRefresh, fetchRaw } from './api';
import { apiBase } from './apiBase';
import { formatApiError } from './authSession';

// Client for the backend's auth + admin endpoints (all under /api/v1, session
// carried by httpOnly cookies — see utils/api.js).

const url = (path) => `${apiBase()}/api/v1${path}`;

const json = async (path, { method = 'GET', body } = {}) => {
  const res = await fetchWithRefresh(url(path), {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(formatApiError(data, res.status));
  return data;
};

/**
 * GET /auth/me — the app gate. Goes through the shared wrapper, so an expired
 * access token is refreshed before the caller ever sees a 401; a 401 that
 * reaches the caller means the session is genuinely gone. Returns the Response.
 */
export const fetchMe = () => fetchWithRefresh(url('/auth/me'));

/**
 * Like fetchMe but bypasses the refresh/redirect wrapper (login page: "already signed
 * in?"). Resolves to the /auth/me body, or null when there is no session.
 */
export const probeSession = async () => {
  try {
    const res = await fetchRaw(url('/auth/me'));
    return res.ok ? await res.json() : null;
  } catch (_) {
    return null;
  }
};

/** POST /auth/login → { user, organization, role }; cookies are set by the server. */
export const login = ({ email, password, organizationUuid }) =>
  json('/auth/login', {
    method: 'POST',
    body: {
      email,
      password,
      ...(organizationUuid ? { organization_uuid: organizationUuid } : {}),
    },
  });

/** Organizations the current user belongs to: [{ uuid, name, role }]. */
export const fetchOrganizations = () => json('/organizations');

/**
 * Switch the active organization; the new tokens are already in cookies when
 * this resolves, so the caller can reload.
 */
export const changeOrganization = (organizationUuid) =>
  json(`/auth/change_organization/${organizationUuid}`, { method: 'POST' });

/**
 * Clear the session server-side. The logout path is a session path, so a 401
 * here is never refreshed or redirected — we are already leaving.
 */
export const logout = () => fetchRaw(url('/auth/logout'), { method: 'POST' }).catch(() => {});

// Admin management (role admin / super_admin only).
export const adminApi = {
  listOrganizations: () => json('/admin/organizations'),
  createOrganization: (body) => json('/admin/organizations', { method: 'POST', body }),
  listUsers: () => json('/admin/users'),
  createUser: (body) => json('/admin/users', { method: 'POST', body }),
  updateUser: (id, body) => json(`/admin/users/${id}`, { method: 'PATCH', body }),
  setMembership: (organizationUuid, userId, role) =>
    json(`/admin/organizations/${organizationUuid}/members/${userId}`, { method: 'PUT', body: { role } }),
  removeMembership: (organizationUuid, userId) =>
    json(`/admin/organizations/${organizationUuid}/members/${userId}`, { method: 'DELETE' }),
};
