export type CacheEntry<T> = {
  data: T;
  lastChanged: string; // ISO from /version
  cachedAt: string;    // ISO when we cached locally
  etag?: string;       // optional ETag from /version
};

const DEFAULT_VERSION_URL = "/api/dashboard/version";
const LS_PREFIX = ""; // e.g., "curricalign:" if you want namespacing
const DEFAULT_TTL_MS = 1000 * 60 * 60 * 24 * 7; // 7 days fallback if version is unreachable

// ---- BroadcastChannel for cross-tab invalidation (optional) ----
const BC_NAME = "dash-cache";
const bc: BroadcastChannel | null =
  typeof window !== "undefined" && "BroadcastChannel" in window
    ? new BroadcastChannel(BC_NAME)
    : null;

export function broadcastInvalidate(cacheKey: string) {
  bc?.postMessage({ type: "invalidate", cacheKey });
}

if (bc) {
  bc.addEventListener("message", (ev: MessageEvent) => {
    const msg = ev?.data;
    if (msg?.type === "invalidate" && typeof msg?.cacheKey === "string") {
      try {
        localStorage.removeItem(msg.cacheKey);
      } catch {}
    }
  });
}

// ---- localStorage helpers ----
function readCache<T>(key: string): CacheEntry<T> | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key);
    if (!raw) return null;
    return JSON.parse(raw) as CacheEntry<T>;
  } catch {
    return null;
  }
}

function writeCache<T>(key: string, entry: CacheEntry<T>) {
  try {
    localStorage.setItem(LS_PREFIX + key, JSON.stringify(entry));
  } catch {}
}

export function clearCache(key: string) {
  try {
    localStorage.removeItem(LS_PREFIX + key);
    broadcastInvalidate(LS_PREFIX + key);
  } catch {}
}

export function peekCache<T>(key: string): CacheEntry<T> | null {
  return readCache<T>(key);
}

export function getLastChangedFromCache(key: string): string | null {
  const c = readCache<unknown>(key);
  return c?.lastChanged ?? null;
}

export function formatLastChanged(iso?: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ---- HTTP helpers ----
async function fetchJSON<T>(
  url: string,
  init?: RequestInit,
  signal?: AbortSignal
): Promise<{ data: T; etag?: string }> {
  const res = await fetch(url, {
    ...init,
    signal,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (res.status === 304) {
    // Caller decides how to handle 304 (usually use cached data)
    // We still return shape-compatible object; data is undefined here.
    return { data: undefined as unknown as T, etag: res.headers.get("ETag") ?? undefined };
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`GET ${url} failed: ${res.status} ${text}`);
  }
  const etag = res.headers.get("ETag") ?? undefined;
  const data = (await res.json()) as T;
  return { data, etag };
}

type VersionResponse = { lastChanged: string };

// ---- Core: version-gated cache fetch ----
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

  // --- 1) Check version endpoint first (cheap)
  // Send If-None-Match with previous ETag to get 304 when unchanged (optional micro-opt)
  const versionInit: RequestInit = {};
  if (cached?.etag) {
    versionInit.headers = { ...(versionInit.headers || {}), "If-None-Match": cached.etag };
  }

  try {
    const vRes = await fetch(versionUrl, {
      ...versionInit,
      signal,
      cache: "no-store",
      headers: {
        ...(versionInit.headers || {}),
        Accept: "application/json",
      },
    });

    if (vRes.status === 304 && cached) {
      // Version unchanged → serve cache
      return { data: cached.data, lastChanged: cached.lastChanged };
    }

    if (!vRes.ok) {
      throw new Error(`Version check failed: ${vRes.status}`);
    }

    const vEtag = vRes.headers.get("ETag") ?? undefined;
    const { lastChanged } = (await vRes.json()) as VersionResponse;

    // If cache exists and version matches → serve cache
    if (cached && cached.lastChanged === lastChanged) {
      return { data: cached.data, lastChanged: cached.lastChanged };
    }

    // --- 2) Version changed OR no cache → fetch fresh data
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
    // --- 3) /version unreachable: optional stale fallback with TTL
    if (cached && opts?.allowStaleOnVersionError !== false) {
      const age = Date.now() - new Date(cached.cachedAt).getTime();
      if (age <= ttlMs) {
        // Serve stale (bounded)
        return { data: cached.data, lastChanged: cached.lastChanged };
      }
    }
    // As a last resort, try direct fetch (no version guard)
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

// ---- Convenience utilities ----

/** Manually set cache (e.g., after optimistic updates). */
export function setCache<T>(cacheKey: string, data: T, lastChangedISO: string, etag?: string) {
  writeCache<T>(cacheKey, {
    data,
    lastChanged: lastChangedISO,
    cachedAt: new Date().toISOString(),
    etag,
  });
  broadcastInvalidate(LS_PREFIX + cacheKey); // notify other tabs to reload their copy
}

/** Invalidate multiple keys at once. */
export function clearMany(keys: string[]) {
  for (const k of keys) clearCache(k);
}

/** True if a cached entry exists and matches a given lastChanged value. */
export function isCacheVersion(cacheKey: string, lastChangedISO: string): boolean {
  const c = readCache<unknown>(cacheKey);
  return !!(c && c.lastChanged === lastChangedISO);
}