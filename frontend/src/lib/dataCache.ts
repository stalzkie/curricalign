// src/lib/dataCache.ts

export type CacheEntry<T> = {
  data: T;
  lastChanged: string; // ISO from /version
  cachedAt: string;    // ISO when we cached locally
  etag?: string;       // optional ETag from /version
};

const DEFAULT_VERSION_URL = '/api/dashboard/version';
const LS_PREFIX = ''; // e.g., 'curricalign:' if you want namespacing
const DEFAULT_TTL_MS = 1000 * 60 * 60 * 24 * 7; // 7 days fallback if version is unreachable

/* =============================================================================
   BroadcastChannel for cross-tab invalidation
============================================================================= */

const BC_NAME = 'dash-cache';
const hasWindow = typeof window !== 'undefined';
const hasBC = hasWindow && 'BroadcastChannel' in window;

const bc: BroadcastChannel | null = hasBC ? new BroadcastChannel(BC_NAME) : null;

export function broadcastInvalidate(cacheKey: string) {
  bc?.postMessage({ type: 'invalidate', cacheKey });
}

if (bc) {
  bc.addEventListener('message', (ev: MessageEvent) => {
    const msg = ev?.data;
    if (msg?.type === 'invalidate' && typeof msg?.cacheKey === 'string') {
      try {
        if (!hasWindow || !('localStorage' in window)) return;
        localStorage.removeItem(msg.cacheKey);
      } catch {
        /* ignore */
      }
    }
  });
}

/* =============================================================================
   localStorage helpers (SSR safe)
============================================================================= */

function k(key: string) {
  return LS_PREFIX + key;
}

function readCache<T>(key: string): CacheEntry<T> | null {
  try {
    if (!hasWindow || !('localStorage' in window)) return null;
    const raw = localStorage.getItem(k(key));
    if (!raw) return null;
    return JSON.parse(raw) as CacheEntry<T>;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, entry: CacheEntry<T>) {
  try {
    if (!hasWindow || !('localStorage' in window)) return;
    localStorage.setItem(k(key), JSON.stringify(entry));
  } catch {
    /* ignore */
  }
}

export function clearCache(key: string) {
  try {
    if (!hasWindow || !('localStorage' in window)) return;
    localStorage.removeItem(k(key));
    broadcastInvalidate(k(key));
  } catch {
    /* ignore */
  }
}

export function peekCache<T>(key: string): CacheEntry<T> | null {
  return readCache<T>(key);
}

export function getLastChangedFromCache(key: string): string | null {
  const c = readCache<unknown>(key);
  return c?.lastChanged ?? null;
}

export function formatLastChanged(iso?: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/* =============================================================================
   HTTP helpers
============================================================================= */

async function fetchJSON<T>(
  url: string,
  init?: RequestInit,
  signal?: AbortSignal
): Promise<{ data: T; etag?: string }> {
  const res = await fetch(url, {
    ...init,
    signal,
    cache: 'no-store',
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (res.status === 304) {
    // Callers treat 304 as "use cached"; we return a compatible shape
    return { data: undefined as unknown as T, etag: res.headers.get('ETag') ?? undefined };
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`GET ${url} failed: ${res.status} ${text}`);
  }

  const etag = res.headers.get('ETag') ?? undefined;
  const data = (await res.json()) as T;
  return { data, etag };
}

type VersionResponse = { lastChanged: string };

/* =============================================================================
   Core: version-gated cache fetch
============================================================================= */

/**
 * Fetch dashboard data with version guarding:
 *  1) GET versionUrl (sends If-None-Match if we have an ETag)
 *     - if 304 and we have cache → return cache
 *     - if 200, compare lastChanged with cache
 *  2) If changed or no cache → GET dataUrl, cache with new version/etag
 *  3) If version fails, optionally serve bounded-stale cache by TTL
 */
export async function getWithVersionCache<T>(
  cacheKey: string,
  dataUrl: string,
  versionUrl: string = DEFAULT_VERSION_URL,
  signal?: AbortSignal,
  opts?: {
    /** Optional TTL as a safety valve if /version is temporarily unreachable. Default 7d. */
    ttlMs?: number;
    /** If true, will still return cached data when /version errors. */
    allowStaleOnVersionError?: boolean;
  }
): Promise<{ data: T; lastChanged: string }> {
  const ttlMs = opts?.ttlMs ?? DEFAULT_TTL_MS;
  const cached = readCache<T>(cacheKey);

  // 1) Check /version first (cheap), with ETag for 304 hits
  const versionInit: RequestInit = {};
  if (cached?.etag) {
    versionInit.headers = { ...(versionInit.headers || {}), 'If-None-Match': cached.etag };
  }

  try {
    const vRes = await fetch(versionUrl, {
      ...versionInit,
      signal,
      cache: 'no-store',
      headers: {
        ...(versionInit.headers || {}),
        Accept: 'application/json',
      },
    });

    if (vRes.status === 304 && cached) {
      return { data: cached.data, lastChanged: cached.lastChanged };
    }

    if (!vRes.ok) {
      throw new Error(`Version check failed: ${vRes.status}`);
    }

    const vEtag = vRes.headers.get('ETag') ?? undefined;
    const { lastChanged } = (await vRes.json()) as VersionResponse;

    // Version same → serve cache
    if (cached && cached.lastChanged === lastChanged) {
      return { data: cached.data, lastChanged: cached.lastChanged };
    }

    // 2) Version changed or no cache → fetch fresh data
    const { data } = await fetchJSON<T>(dataUrl, undefined, signal);
    const entry: CacheEntry<T> = {
      data,
      lastChanged,
      cachedAt: new Date().toISOString(),
      etag: vEtag,
    };
    writeCache<T>(cacheKey, entry);
    return { data, lastChanged };
  } catch (err) {
    // 3) If /version fails, serve bounded-stale cache (TTL) if allowed
    if (cached && opts?.allowStaleOnVersionError !== false) {
      const age = Date.now() - new Date(cached.cachedAt).getTime();
      if (age <= ttlMs) {
        return { data: cached.data, lastChanged: cached.lastChanged };
      }
    }
    // As a last resort, fetch data directly (no version guard)
    if (!signal?.aborted) {
      const { data } = await fetchJSON<T>(dataUrl, undefined, signal);
      const nowIso = new Date().toISOString();
      const entry: CacheEntry<T> = {
        data,
        lastChanged: cached?.lastChanged ?? nowIso,
        cachedAt: nowIso,
        etag: cached?.etag,
      };
      writeCache<T>(cacheKey, entry);
      return { data, lastChanged: entry.lastChanged };
    }
    throw err;
  }
}

/* =============================================================================
   Convenience utilities
============================================================================= */

/** Manually set cache (e.g., after optimistic updates). */
export function setCache<T>(cacheKey: string, data: T, lastChangedISO: string, etag?: string) {
  writeCache<T>(cacheKey, {
    data,
    lastChanged: lastChangedISO,
    cachedAt: new Date().toISOString(),
    etag,
  });
  // notify other tabs to drop their local copy so they re-read on next access
  broadcastInvalidate(k(cacheKey));
}

/** Invalidate multiple keys at once. */
export function clearMany(keys: string[]) {
  for (const key of keys) clearCache(key);
}

/** True if a cached entry exists and matches a given lastChanged value. */
export function isCacheVersion(cacheKey: string, lastChangedISO: string): boolean {
  const c = readCache<unknown>(cacheKey);
  return !!(c && c.lastChanged === lastChangedISO);
}
