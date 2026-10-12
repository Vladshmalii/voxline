import { useEffect, useState } from 'react';
import { modelsApi } from './callApi';
import { loadModelVoices } from './voiceCatalog';

// Fetch once per distinct model on a page, rather than once per agent row.
export function useVoiceLabels(modelIds, enabled) {
  const key = JSON.stringify(enabled ? [...new Set(modelIds.filter(Boolean))].sort() : []);
  const [catalogs, setCatalogs] = useState({});

  useEffect(() => {
    let cancelled = false;
    setCatalogs({});
    const ids = JSON.parse(key);
    Promise.allSettled(ids.map((id) => loadModelVoices(modelsApi, id)))
      .then((results) => {
        if (cancelled) return;
        setCatalogs(Object.fromEntries(results.map((result, index) => [
          ids[index], result.status === 'fulfilled' ? result.value : [],
        ])));
      });
    return () => { cancelled = true; };
  }, [key]);

  return catalogs;
}
