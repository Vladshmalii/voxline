// Public entry point: importing anything from 'i18n' guarantees the namespace
// catalogue is already registered.
import './namespaces';

export {
  LOCALES,
  DEFAULT_LOCALE,
  LOCALE_NAMES,
  STORAGE_KEY,
  registerMessages,
  getMessages,
  createTranslator,
  detectLocale,
  translate,
  resolveText,
} from './registry';
