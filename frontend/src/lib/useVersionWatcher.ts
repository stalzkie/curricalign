// src/lib/useVersionWatcher.ts
'use client';

import { useEffect, useRef, useState } from 'react';
import { getLastChangedISOFromAnyCache } from './dataService';

const VERSION_URL = '/api/dashboard/version';

function parseIsoMs(iso?: string | null): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : 0;
}

/**
 * Watches the dashboard version and returns the latest ISO timestamp.
 * - Uses ETag (If-None-Match) so unchanged versions return 304 (no state change)
 * - Only updates state if the timestamp strictly increases (prevents flapping)
 * - Pauses while the tab is hidden; immediate check on window focus/visibility
 *
 * @param _tableName  (kept for backward compatibility; not used)
 * @param pollMs      base poll interval in ms (default 20s)
 */
export function useVersionWatcher(_tableName?: string, pollMs = 20_000) {
  // Seed from any cached entry so badges don’t jump on first paint.
  const initial = getLastChangedISOFromAnyCache();
  const [lastChanged, setLastChanged] = useState<string | null>(initial);

  const lastChangedRef = useRef<string | null>(initial);
  const etagRef = useRef<string | undefined>(undefined);
  const timerRef = useRef<number | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const nextDelayRef = useRef<number>(pollMs); // adaptive backoff

  useEffect(() => {
    let cancelled = false;

    const clearTimer = () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = (delay: number) => {
      clearTimer();
      nextDelayRef.current = delay;
      timerRef.current = window.setTimeout(tick, delay);
    };

    const setIfAdvanced = (incomingIso: string) => {
      const prevMs = parseIsoMs(lastChangedRef.current);
      const nextMs = parseIsoMs(incomingIso);
      // Only update if strictly newer (guards against jitter/clock skew/regressions)
      if (nextMs > prevMs) {
        lastChangedRef.current = incomingIso;
        setLastChanged(incomingIso);
      }
    };

    const tick = async () => {
      if (cancelled) return;

      // Pause polling while tab is hidden
      if (document.hidden) {
        schedule(nextDelayRef.current);
        return;
      }

      // Cancel any prior request
      inFlight.current?.abort();
      const ac = new AbortController();
      inFlight.current = ac;

      try {
        const res = await fetch(VERSION_URL, {
          cache: 'no-store',
          headers: etagRef.current ? { 'If-None-Match': etagRef.current } : {},
          signal: ac.signal,
        });

        if (res.status === 304) {
          // Unchanged → keep current state, reset delay to base
          schedule(pollMs);
          return;
        }

        if (res.ok) {
          etagRef.current = res.headers.get('ETag') ?? undefined;
          const body = (await res.json()) as { lastChanged?: string };
          if (!cancelled && body?.lastChanged) {
            setIfAdvanced(body.lastChanged);
          }
          // success → reset to base cadence
          schedule(pollMs);
          return;
        }

        // Non-OK → back off (cap at 2 minutes)
        schedule(Math.min(nextDelayRef.current * 2, 120_000));
      } catch {
        // Network/abort → back off (cap at 2 minutes)
        schedule(Math.min(nextDelayRef.current * 2, 120_000));
      }
    };

    const onFocus = () => {
      // Immediate check on refocus, but only if we’re not hidden
      if (!document.hidden) {
        clearTimer();
        // small debounce to let the event loop settle
        timerRef.current = window.setTimeout(tick, 50);
      }
    };

    const onVisibility = () => {
      if (!document.hidden) onFocus();
    };

    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);

    // Kick off immediately
    tick();

    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
      clearTimer();
      inFlight.current?.abort();
    };
  }, [pollMs]);

  return lastChanged; // ISO string or null
}
