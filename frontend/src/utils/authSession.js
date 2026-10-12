// Pure helpers behind the session handling (no env, no DOM) so they can be
// unit-tested with `node --test`.

export const LOGIN_PATH = '/login';

// The only 401 detail a refresh can fix: the access token aged out. Anything
// else (`unauthorized`, `token_invalid`, …) is a broken or missing session —
// refreshing would just burn a round trip, so the user goes to log in.
export const isRefreshable401 = (detail) => detail === 'token_expired';

/** The session endpoints must never go through the refresh-and-retry wrapper. */
export const isSessionPath = (urlStr) =>
  /\/api\/v1\/auth\/(login|refresh|logout)(\?|#|$)/i.test(String(urlStr || ''));

/**
 * Accept only same-app relative paths as a post-login target. Anything that
 * could leave the origin (absolute URLs, `//host`, backslashes) or loop back to
 * the login page falls back to `/`.
 */
export const safeNextPath = (next) => {
  const raw = typeof next === 'string' ? next.trim() : '';
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return '/';
  if (raw === LOGIN_PATH || raw.startsWith(`${LOGIN_PATH}?`) || raw.startsWith(`${LOGIN_PATH}#`)) return '/';
  return raw;
};

/** `/login?next=<current location>` — omits `next` when it would be just `/`. */
export const buildLoginPath = (next) => {
  const target = safeNextPath(next);
  return target === '/' ? LOGIN_PATH : `${LOGIN_PATH}?next=${encodeURIComponent(target)}`;
};

/** Does `url` point at the backend API (relative, or under `base`)? */
export const isApiUrl = (url, base, origin = 'http://localhost') => {
  const raw = String(url || '').trim();
  if (!raw || isSessionPath(raw)) return false;
  const cleanBase = String(base || '').trim().replace(/\/$/, '');
  if (cleanBase && raw.startsWith(`${cleanBase}/api/v1/`)) return true;
  // Same-origin relative URL (dev proxy / nginx): always the app's own backend.
  if (/^\/api\/v1\//i.test(raw)) return true;
  try {
    const u = new URL(raw, origin);
    if (!/^\/api\/v1\//i.test(u.pathname)) return false;
    if (isSessionPath(u.pathname + u.search)) return false;
    const baseHost = cleanBase ? new URL(cleanBase, origin).host : new URL(origin).host;
    return u.host === baseHost;
  } catch (_) {
    return false;
  }
};

/** Flatten GET /auth/me ({user, organization, role}) into the app's user object. */
export const normalizeMe = (data) => {
  if (!data || typeof data !== 'object') return null;
  const user = data.user || {};
  return {
    ...user,
    organization: data.organization || null,
    account_role: data.role ?? null,
  };
};

/** Human-readable text of a FastAPI error body (string or validation list). */
export const formatApiError = (data, status) => {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : '';
        return loc ? `${loc}: ${e.msg}` : e.msg;
      })
      .join('; ');
  }
  return `Request failed (${status})`;
};
