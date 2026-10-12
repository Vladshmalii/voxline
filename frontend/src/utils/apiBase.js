// Single backend host for every API call and the WS playground.
// `VITE_API_URL` unset -> local default; set to an empty string -> same origin
// (relative URLs, e.g. behind the nginx /api proxy).
export const DEFAULT_API_URL = 'http://localhost:8086';

export const apiBase = () => {
  const raw = import.meta.env.VITE_API_URL;
  return (raw === undefined ? DEFAULT_API_URL : String(raw)).trim().replace(/\/$/, '');
};

/** Absolute URL object for a path under the backend (resolves same-origin bases). */
export const apiUrlFor = (path) => new URL(`${apiBase()}${path}`, window.location.origin);
