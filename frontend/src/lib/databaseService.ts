// src/lib/databaseService.ts
import { supabase } from "@/lib/supabaseClients";
import { setCache, clearCache } from "./dataCache";

export type DbCacheEntry<T = any> = {
  data: T[];
  lastChanged: string; // ISO when the table last changed (from table_versions.updated_at)
  cachedAt: string;    // ISO when we cached locally
};

const CK = (table: string) => `db:${table}`;

/** Utility: stringify any unknown error safely */
function toErrMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  try {
    return typeof err === "string" ? err : JSON.stringify(err ?? {});
  } catch {
    return String(err);
  }
}

/** Utility: ensure a clean, unique list of valid column names */
function sanitizeColumns(cols?: string[]): string[] {
  const out = (cols ?? [])
    .filter((c): c is string => typeof c === "string" && c.trim().length > 0)
    .map((c) => c.trim());
  // remove duplicates while preserving order
  return Array.from(new Set(out));
}

/** Fetch the change-version (updated_at) for a table from public.table_versions. */
export async function getTableLastChanged(table: string): Promise<string> {
  try {
    const { data, error } = await supabase
      .from("table_versions")
      .select("updated_at")
      .eq("table_name", table)
      .maybeSingle();

    if (error) {
      // Wrap as real Error so callers see the details
      throw new Error(
        JSON.stringify(
          { where: "getTableLastChanged", table, message: error.message, details: error.details, hint: error.hint, code: error.code },
          null,
          2
        )
      );
    }

    // If the row isn't there yet, treat as "ancient" so first fetch proceeds and seeds cache
    const iso = data?.updated_at ? new Date(data.updated_at).toISOString() : new Date(0).toISOString();
    return iso;
  } catch (e) {
    // Re-throw as an Error if something odd was thrown
    throw new Error(toErrMessage(e));
  }
}

/**
 * Fetch rows from a table with a projection (columns list).
 * Optionally supports range() for simple pagination.
 */
export async function fetchTableRows<T = any>(
  table: string,
  columns: string[],
  opts?: { from?: number; to?: number }
): Promise<T[]> {
  const cleaned = sanitizeColumns(columns);
  const selectCols = cleaned.length ? cleaned.join(",") : "*";

  // Helpful debug to see exactly what we’re querying
  // (You can mute this later.)
  // eslint-disable-next-line no-console
  console.info(`[databaseService] select ${table} ->`, selectCols);

  try {
    let q = supabase.from(table).select(selectCols);

    if (typeof opts?.from === "number" && typeof opts?.to === "number") {
      q = q.range(opts.from, opts.to);
    }

    const { data, error } = await q;

    if (error) {
      // Wrap as Error so React overlay shows message instead of "{}"
      throw new Error(
        JSON.stringify(
          { where: "fetchTableRows", table, select: selectCols, message: error.message, details: error.details, hint: error.hint, code: error.code },
          null,
          2
        )
      );
    }
    return (data ?? []) as T[];
  } catch (e) {
    // Re-wrap unknown throws
    throw new Error(toErrMessage(e));
  }
}

/**
 * Version-gated cached fetch.
 * - Reads version from table_versions
 * - Returns cached rows if version unchanged
 * - Otherwise fetches rows and caches them with setCache
 *
 * @param table Supabase table name (e.g., "course_alignment_scores_clean")
 * @param columns Columns to select (keep this tight for performance)
 * @param opts Optional paging + stale behavior
 */
export async function getDbRowsCached<T = any>(
  table: string,
  columns: string[],
  opts?: {
    from?: number;
    to?: number;
    /** Allow returning stale cache when version read fails. Default: true */
    allowStaleOnVersionError?: boolean;
  }
): Promise<T[]> {
  const cacheKey = CK(table);
  const allowStale = opts?.allowStaleOnVersionError ?? true;

  // 1) Read current lastChanged from DB
  let lastChanged: string | null = null;
  try {
    lastChanged = await getTableLastChanged(table);
  } catch (err) {
    // Version check failed (missing table_versions or RLS). Optionally serve stale.
    if (!allowStale) throw new Error(toErrMessage(err));

    const cachedRaw = safeReadCache<T>(cacheKey);
    if (cachedRaw) return cachedRaw.data;
    // Fall through to a direct fetch so UI isn’t stuck
  }

  // 2) If we have cache and versions match → return cached
  const cached = safeReadCache<T>(cacheKey);
  if (lastChanged && cached?.lastChanged === lastChanged) {
    return cached.data;
  }

  // 3) Fetch fresh rows
  const rows = await fetchTableRows<T>(table, columns, { from: opts?.from, to: opts?.to });

  // 4) Save cache (also BroadcastChannel invalidation to other tabs via setCache)
  const finalLastChanged = lastChanged ?? new Date().toISOString();
  setCache(cacheKey, rows, finalLastChanged);

  return rows;
}

/**
 * Always fetch fresh (ignores local cache) and then refresh the cache with the
 * latest version from table_versions if available.
 */
export async function getDbRowsFresh<T = any>(
  table: string,
  columns: string[],
  opts?: { from?: number; to?: number }
): Promise<T[]> {
  const cacheKey = CK(table);
  const rows = await fetchTableRows<T>(table, columns, { from: opts?.from, to: opts?.to });
  let lastChanged = new Date().toISOString();
  try {
    lastChanged = await getTableLastChanged(table);
  } catch {
    // ignore version errors; still cache with now()
  }
  setCache(cacheKey, rows, lastChanged);
  return rows;
}

/** Manually invalidate one table’s cache (and notify other tabs). */
export function invalidateDbCache(table: string) {
  clearCache(CK(table));
}

/** Bulk invalidate multiple tables. */
export function invalidateManyDbCaches(tables: string[]) {
  for (const t of tables) clearCache(CK(t));
}

/** Utility: safe read of your cache entry from localStorage (mirrors dataCache’s storage). */
function safeReadCache<T = any>(key: string): DbCacheEntry<T> | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as DbCacheEntry<T>;
  } catch {
    return null;
  }
}
