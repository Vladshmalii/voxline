import { Component } from 'react';
import { translate } from 'i18n';

// A lazily-imported chunk can 404 when the app was deployed while a tab was
// open (filenames are content-hashed, so the old chunk no longer exists).
// In that case the only fix is to reload and pull the fresh manifest.
const isChunkLoadError = (error) => {
  const message = error?.message || '';
  return (
    error?.name === 'ChunkLoadError' ||
    /Loading chunk \d+ failed/i.test(message) ||
    /Failed to fetch dynamically imported module/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message)
  );
};

// Remember the last forced reload so a chunk that stays broken even after a
// fresh load doesn't trap the user in an infinite reload loop.
const RELOAD_KEY = 'chunk-reload-ts';
const RELOAD_COOLDOWN_MS = 10000;

export class ChunkErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    if (!isChunkLoadError(error)) return;

    const lastReload = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
    if (Date.now() - lastReload > RELOAD_COOLDOWN_MS) {
      sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
      window.location.reload();
    }
  }

  render() {
    if (this.state.hasError) {
      // Shown only if a reload was just attempted and the chunk is still
      // missing (cooldown active), so we don't loop forever.
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16px',
            fontFamily: 'sans-serif',
            color: '#666',
          }}
        >
          <p>{translate('system.chunkFailed')}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              padding: '10px 20px',
              borderRadius: '8px',
              border: '1px solid #ccc',
              background: '#fff',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            {translate('system.reload')}
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
