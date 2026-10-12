import { useEffect, useRef } from 'react';

export const AUTO_REFRESH_MS = 10000;

/**
 * Background polling for a view that has no push channel.
 *
 * Calls `callback` every `interval` ms, except that it
 *   - waits while the tab is hidden (document.hidden) and fires one immediate
 *     refresh when the tab becomes visible again;
 *   - waits while `paused` is true (pass "a modal is open" / "a form is being
 *     edited"); when `paused` flips back to false it refreshes right away;
 *   - never overlaps itself: a tick is skipped while the previous callback's
 *     promise is still pending.
 *
 * `callback` should return a promise (or nothing) and should NOT show loading
 * skeletons/spinners — it is a silent re-read. The latest callback is always
 * used, so it may close over fresh filters/pagination without restarting the
 * timer.
 *
 * @param {() => (Promise<unknown>|void)} callback
 * @param {{ interval?: number, enabled?: boolean, paused?: boolean }} [options]
 */
export const useAutoRefresh = (callback, { interval = AUTO_REFRESH_MS, enabled = true, paused = false } = {}) => {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const inFlight = useRef(false);

  useEffect(() => {
    if (!enabled || paused) return undefined;

    const run = async () => {
      if (document.hidden || inFlight.current) return;
      inFlight.current = true;
      try {
        await callbackRef.current();
      } catch {
        // Background refreshes fail silently; the next tick tries again.
      } finally {
        inFlight.current = false;
      }
    };

    const timer = setInterval(run, interval);
    const onVisibility = () => {
      if (!document.hidden) run();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, paused, interval]);
};
