// src/lib/databaseService.ts
import { supabase } from '@/lib/supabaseClients';
import { setCache, clearCache } from './dataCache';

/* =============================================================================
   Types & Small Utils
============================================================================= */

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
    return typeof err === 'string' ? err : JSON.stringify(err ?? {});
  } catch {
    return String(err);
  }
}

/** Utility: ensure a clean, unique list of valid column names */
function sanitizeColumns(cols?: string[]): string[] {
  const out = (cols ?? [])
    .filter((c): c is string => typeof c === 'string' && c.trim().length > 0)
    .map((c) => c.trim());
  // remove duplicates while preserving order
  return Array.from(new Set(out));
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

/* =============================================================================
   Version: table_versions helpers
============================================================================= */

/** Fetch the change-version (updated_at) for a table from public.table_versions. */
export async function getTableLastChanged(table: string): Promise<string> {
  try {
    const { data, error } = await supabase
      .from('table_versions')
      .select('updated_at')
      .eq('table_name', table)
      .maybeSingle();

    if (error) {
      throw new Error(
        JSON.stringify(
          {
            where: 'getTableLastChanged',
            table,
            message: error.message,
            details: (error as any)?.details,
            hint: (error as any)?.hint,
            code: (error as any)?.code,
          },
          null,
          2
        )
      );
    }

    // If the row isn't there yet, treat as "ancient" so first fetch proceeds and seeds cache
    const iso = data?.updated_at
      ? new Date(data.updated_at).toISOString()
      : new Date(0).toISOString();
    return iso;
  } catch (e) {
    throw new Error(toErrMessage(e));
  }
}

/* =============================================================================
   Basic Fetchers
============================================================================= */

/**
 * Fetch rows from a table with a projection (columns list).
 * Optionally supports range() for simple pagination (offset/limit).
 * Prefer keyset pagination helpers for big tables.
 */
export async function fetchTableRows<T = any>(
  table: string,
  columns: string[],
  opts?: { from?: number; to?: number }
): Promise<T[]> {
  const cleaned = sanitizeColumns(columns);
  const selectCols = cleaned.length ? cleaned.join(',') : '*';

  // eslint-disable-next-line no-console
  console.info(`[databaseService] select ${table} ->`, selectCols);

  try {
    let q = supabase.from(table).select(selectCols);

    if (typeof opts?.from === 'number' && typeof opts?.to === 'number') {
      q = q.range(opts.from, opts.to);
    }

    const { data, error } = await q;

    if (error) {
      throw new Error(
        JSON.stringify(
          {
            where: 'fetchTableRows',
            table,
            select: selectCols,
            message: error.message,
            details: (error as any)?.details,
            hint: (error as any)?.hint,
            code: (error as any)?.code,
          },
          null,
          2
        )
      );
    }
    return (data ?? []) as T[];
  } catch (e) {
    throw new Error(toErrMessage(e));
  }
}

/* =============================================================================
   Cached Fetchers (version-gated)
============================================================================= */

/**
 * Version-gated cached fetch.
 * - Reads version from table_versions
 * - Returns cached rows if version unchanged
 * - Otherwise fetches rows and caches them with setCache
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
    if (!allowStale) throw new Error(toErrMessage(err));
    const cachedRaw = safeReadCache<T>(cacheKey);
    if (cachedRaw) return cachedRaw.data;
    // fall through to direct fetch
  }

  // 2) If we have cache and versions match → return cached
  const cached = safeReadCache<T>(cacheKey);
  if (lastChanged && cached?.lastChanged === lastChanged) {
    return cached.data;
  }

  // 3) Fetch fresh rows
  const rows = await fetchTableRows<T>(table, columns, {
    from: opts?.from,
    to: opts?.to,
  });

  // 4) Cache
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
  const rows = await fetchTableRows<T>(table, columns, {
    from: opts?.from,
    to: opts?.to,
  });
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

/* =============================================================================
   Keyset Pagination (fast scrolling lists)
============================================================================= */

export type KeysetPageArgs = {
  table: string;                        // e.g., 'jobs'
  key: string;                          // e.g., 'job_id' (indexed/monotonic)
  select: string;                       // e.g., 'job_id,title,company,created_at'
  after?: number | string | null;       // last seen key (exclusive)
  limit?: number;                       // default 200
  asc?: boolean;                        // default true
  /** Server-side ilike filters: { columnName: 'substr' } */
  ilike?: Record<string, string | undefined>;
};

/** Get a single keyset page. */
export async function getKeysetPage<T = any>({
  table,
  key,
  select,
  after = null,
  limit = 200,
  asc = true,
  ilike = {},
}: KeysetPageArgs): Promise<T[]> {
  try {
    let q = supabase.from(table).select(select);

    if (after !== null && after !== undefined) {
      q = asc ? q.gt(key, after) : q.lt(key, after);
    }

    q = q.order(key, { ascending: asc }).limit(limit);

    for (const [col, val] of Object.entries(ilike)) {
      if (val && String(val).trim().length > 0) {
        q = q.ilike(col, `%${String(val).trim()}%`);
      }
    }

    const { data, error } = await q;
    if (error) {
      throw new Error(
        JSON.stringify(
          {
            where: 'getKeysetPage',
            table,
            key,
            select,
            message: error.message,
            details: (error as any)?.details,
            hint: (error as any)?.hint,
            code: (error as any)?.code,
          },
          null,
          2
        )
      );
    }
    return (data ?? []) as T[];
  } catch (e) {
    throw new Error(toErrMessage(e));
  }
}

/* =============================================================================
   “Unused only” helpers for FK dropdowns (via views or RPC)
============================================================================= */

export async function getJobsUnusedForSkills() {
  const { data, error } = await supabase
    .from('jobs_unused_for_skills')
    .select('job_id,title,company,created_at')
    .order('created_at', { ascending: false });

  if (error) throw new Error(toErrMessage(error));
  return data ?? [];
}

export async function getCoursesUnusedForSkills() {
  const { data, error } = await supabase
    .from('courses_unused_for_skills')
    .select('course_id,course_code,course_title,created_at')
    .order('created_at', { ascending: false });

  if (error) throw new Error(toErrMessage(error));
  return data ?? [];
}

/* =============================================================================
   Fast Mutations
============================================================================= */

/**
 * Insert one or many rows without returning the inserted data.
 * Supabase JS v2 returns rows **only** if you chain `.select()`.
 * So to minimize round-trips, we just call `.insert(rows)` and do not select.
 */
export async function insertMinimal(
  table: string,
  payload: Record<string, any> | Record<string, any>[]
) {
  const rows = Array.isArray(payload) ? payload : [payload];
  const { error } = await supabase.from(table).insert(rows);
  if (error) throw new Error(toErrMessage(error));
}

/** Update rows with a simple equality condition on a column. */
export async function updateWhere(
  table: string,
  whereCol: string,
  whereVal: string | number,
  payload: Record<string, any>
) {
  const { error } = await supabase.from(table).update(payload).eq(whereCol, whereVal);
  if (error) throw new Error(toErrMessage(error));
}

/** Delete rows with a simple equality condition on a column. */
export async function deleteWhere(
  table: string,
  whereCol: string,
  whereVal: string | number
) {
  const { error } = await supabase.from(table).delete().eq(whereCol, whereVal);
  if (error) throw new Error(toErrMessage(error));
}

/* =============================================================================
   Realtime subscription helper
============================================================================= */

/**
 * Subscribe to realtime changes for a table.
 * Returns an unsubscribe function.
 */
export function subscribeTable<T extends Record<string, any>>(
  table: string,
  onEvent: (e: {
    eventType: 'INSERT' | 'UPDATE' | 'DELETE';
    new?: T;
    old?: T;
  }) => void
) {
  const ch = supabase
    .channel(`realtime:${table}`)
    .on('postgres_changes', { event: '*', schema: 'public', table }, (payload: any) => {
      onEvent({
        eventType: payload.eventType,
        new: payload.new,
        old: payload.old,
      });
    })
    .subscribe();

  return () => {
    supabase.removeChannel(ch);
  };
}
