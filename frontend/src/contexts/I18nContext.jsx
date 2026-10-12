import { createContext, useContext, useMemo, useState } from 'react';
import { LOCALES, STORAGE_KEY, createTranslator, detectLocale } from 'i18n';

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(detectLocale);

  const value = useMemo(() => {
    const setLocale = (next) => {
      if (!LOCALES.includes(next)) return;
      localStorage.setItem(STORAGE_KEY, next);
      setLocaleState(next);
    };
    // `t` is recreated per locale, so every consumer re-renders on a switch.
    return { locale, setLocale, t: createTranslator(locale), locales: LOCALES };
  }, [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
}
