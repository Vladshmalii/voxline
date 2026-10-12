// Session handling for every call to the Voxline API.
//
// Tokens are httpOnly cookies issued by the backend (`access_token` +
// `refresh_token`). The frontend never reads, writes or forwards them: it only
// sets `credentials: 'include'` so the browser attaches them. There is
// deliberately no cookie helper in this module — a token the frontend can touch
// is a token XSS can steal. No Authorization header is sent.

import { apiBase } from './apiBase';
import { isApiUrl, isRefreshable401, buildLoginPath, LOGIN_PATH } from './authSession';

let _nativeFetch =
  typeof window !== 'undefined' && window.fetch ? window.fetch.bind(window) : () => Promise.reject(new Error('fetch'));

let refreshInFlight = null;
let redirectingToLogin = false;

const REFRESH_PATH = '/api/v1/auth/refresh';

/**
 * Leave for the in-app login page, remembering where the user was (`?next=`).
 * Guarded: several in-flight requests can fail auth at once, and each would
 * otherwise trigger its own navigation. A no-op while already on /login.
 */
export const redirectToLogin = (next) => {
  if (redirectingToLogin || window.location.pathname === LOGIN_PATH) return;
  redirectingToLogin = true;
  const here = next ?? `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.assign(buildLoginPath(here));
};

/**
 * Does this URL point at the backend API and carry the session cookies?
 * Handles relative URLs (/api/v1/...) and the configured API base.
 */
export function isProtectedApiUrl(url) {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
  return isApiUrl(url, apiBase(), origin);
}

function readSkipAuthHeader(init) {
  const h = init?.headers;
  if (!h) return false;
  if (h instanceof Headers) return h.get('X-Skip-Auth-Refresh') === '1';
  return h['X-Skip-Auth-Refresh'] === '1' || h['x-skip-auth-refresh'] === '1';
}

/**
 * Ask the backend for a new access token. The refresh token rides along as an
 * httpOnly cookie and the rotated tokens come back as Set-Cookie — nothing is
 * read from the response body.
 */
const refreshSession = async () => {
  const response = await _nativeFetch(`${apiBase()}${REFRESH_PATH}`, {
    method: 'POST',
    credentials: 'include',
  });
  if (!response.ok) {
    throw new Error(`Session refresh failed (${response.status})`);
  }
};

/** One refresh at a time: parallel 401s share a single round trip. */
function refreshSessionDeduped() {
  if (!refreshInFlight) {
    refreshInFlight = refreshSession().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function headersToPlain(optionsHeaders) {
  if (!optionsHeaders) return {};
  if (optionsHeaders instanceof Headers) {
    const o = {};
    optionsHeaders.forEach((v, k) => {
      o[k] = v;
    });
    return o;
  }
  return { ...optionsHeaders };
}

function resolveUrlString(input) {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  if (input && typeof input.url === 'string') return input.url;
  return '';
}

/** The `detail` of a FastAPI error body, read without consuming the response. */
async function readErrorDetail(response) {
  try {
    const data = await response.clone().json();
    return typeof data?.detail === 'string' ? data.detail : null;
  } catch (_) {
    return null;
  }
}

async function executeWithAuthRetry(input, init) {
  const opts = { ...init };
  const headers = headersToPlain(opts.headers);
  const isFormData = typeof FormData !== 'undefined' && opts.body instanceof FormData;

  if (opts.body != null && !isFormData && !headers['Content-Type'] && !headers['content-type']) {
    headers['Content-Type'] = 'application/json';
  }

  const creds = opts.credentials ?? 'include';
  const exec = () =>
    _nativeFetch(input, {
      ...opts,
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      credentials: creds,
    });

  const response = await exec();
  if (response.status !== 401) return response;

  // A broken session cannot be refreshed — send the user to log in instead of
  // spending a round trip on the refresh endpoint.
  const detail = await readErrorDetail(response);
  if (!isRefreshable401(detail)) {
    redirectToLogin();
    return response;
  }

  try {
    await refreshSessionDeduped();
  } catch (refreshError) {
    redirectToLogin();
    return response;
  }

  // Exactly one retry: if it 401s again the refresh did not help, and looping
  // would hammer the backend.
  return exec();
}

export function installGlobalAuthenticatedFetch() {
  if (typeof window === 'undefined' || window.__VOXLINE_AUTH_FETCH__) {
    return;
  }
  window.__VOXLINE_AUTH_FETCH__ = true;

  const native = window.fetch.bind(window);
  _nativeFetch = native;

  window.fetch = async function patchedFetch(input, init = {}) {
    const url = resolveUrlString(input);

    if (readSkipAuthHeader(init) || !isProtectedApiUrl(url)) {
      return native(input, init);
    }

    if (input instanceof Request) {
      return native(input, init);
    }

    return executeWithAuthRetry(input, init);
  };
}

export const fetchWithRefresh = (url, options = {}) =>
  window.fetch(url, { ...options, credentials: options.credentials ?? 'include' });

/** Plain credentialed fetch that bypasses the refresh-and-redirect wrapper. */
export const fetchRaw = (url, options = {}) =>
  _nativeFetch(url, { ...options, credentials: options.credentials ?? 'include' });
