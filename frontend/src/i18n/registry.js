// Message registry for the Voxline panel.
//
// Messages are grouped into namespaces (`nav`, `flows`, `steps`, …), each
// registered from its own module under `namespaces/`. A feature ships its own
// namespace and nothing else has to change — that is the point of
// `registerMessages` being public.
//
// Lookup is by dotted path: t('steps.branchLabels'). A key missing from the
// active locale falls back to DEFAULT_LOCALE; a key missing everywhere returns
// the key itself, so gaps show up in the UI instead of rendering as blanks.
//
// This module holds no namespace imports on purpose: namespaces import *from*
// it, and `i18n/index.js` pulls them in. Keeping the registry at the bottom of
// the dependency graph avoids an import cycle.

export const LOCALES = ['en', 'ru'];
export const DEFAULT_LOCALE = 'en';

export const LOCALE_NAMES = {
  en: 'English',
  ru: 'Русский',
};

const registry = Object.fromEntries(LOCALES.map((locale) => [locale, {}]));

/**
 * Add a namespace to the catalogue.
 *
 * @param {string} namespace  top-level key, e.g. 'flows'
 * @param {object} messages   { en: {...}, ru: {...} } — nesting is free-form
 */
export const registerMessages = (namespace, messages) => {
  LOCALES.forEach((locale) => {
    if (messages[locale]) registry[locale][namespace] = messages[locale];
  });
};

export const getMessages = (locale) => registry[locale] || registry[DEFAULT_LOCALE];

const lookup = (locale, path) =>
  path.split('.').reduce((node, part) => (node == null ? undefined : node[part]), registry[locale]);

/** Replaces {placeholders} with values from `params`. */
const interpolate = (template, params) => {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    params[name] === undefined ? match : String(params[name])
  );
};

/**
 * Builds a `t(key, params)` for a locale. A message may be a string or a
 * function of `params` — the latter for text that needs real logic (plurals,
 * conditional clauses) rather than plain substitution.
 */
export const createTranslator = (locale) => (key, params) => {
  if (!key) return '';
  const value = lookup(locale, key) ?? lookup(DEFAULT_LOCALE, key);
  if (value === undefined) return key;
  if (typeof value === 'function') return value(params || {});
  return interpolate(String(value), params);
};

export const STORAGE_KEY = 'lang';

/**
 * Active locale without React: the stored choice, else the browser language,
 * else the default. `I18nProvider` seeds its state from this, so the two never
 * disagree.
 */
export const detectLocale = () => {
  const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
  if (saved && LOCALES.includes(saved)) return saved;
  const browser = (typeof navigator !== 'undefined' ? navigator.language || '' : '').slice(0, 2);
  return LOCALES.includes(browser) ? browser : DEFAULT_LOCALE;
};

/**
 * Translate outside the React tree — class components and plain modules that
 * cannot call `useI18n`. Inside components prefer the hook: it re-renders on a
 * locale switch, this does not.
 */
export const translate = (key, params) => createTranslator(detectLocale())(key, params);

/**
 * Reads a translatable slot off a declarative spec (form field, table column).
 * `labelKey` wins over a literal `label`, so specs stay plain data and the
 * render layer decides the language:
 *
 *   { name: 'url', labelKey: 'integrations.fields.url' }
 *   { name: 'type', label: 'find_transaction' }   // literal: an API value
 *   { name: 'x', hintKey: 'steps.hints.y', hintParams: { label } }
 */
export const resolveText = (t, spec, slot = 'label') => {
  if (!spec) return undefined;
  const key = spec[`${slot}Key`];
  if (key) return t(key, spec[`${slot}Params`]);
  return spec[slot];
};
