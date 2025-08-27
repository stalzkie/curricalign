// src/lib/useVersionWatcher.ts
'use client';

import { useEffect, useRef, useState } from "react";
import { getLastChangedISOFromAnyCache } from "./dataService";

export function useVersionWatcher() {
  const [lastChanged, setLastChanged] = useState<string | null>(getLastChangedISOFromAnyCache());
  const timer = useRef<number | null>(null);

  useEffect(() => {
    const onFocus = () => {
      const iso = getLastChangedISOFromAnyCache();
      setLastChanged(iso);
    };
    window.addEventListener("focus", onFocus);

    // Optional very-light refresh every 60s (does NOT fetch data; just updates label from cache)
    timer.current = window.setInterval(onFocus, 60_000);

    return () => {
      window.removeEventListener("focus", onFocus);
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  return lastChanged; // ISO string or null
}
