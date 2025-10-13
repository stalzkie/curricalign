// src/components/tables/TableViewer.tsx
'use client';

import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { supabase } from '@/lib/supabaseClients';
import { invalidateDbCache } from '@/lib/databaseService';
import { RiEyeLine, RiEdit2Line, RiDeleteBinLine, RiAlertLine } from 'react-icons/ri';
import AddRowModal from './AddRowModal';
import ViewRowModal from './ViewRowModal';
import UpdateBadge from '../dashboard/UpdateBadge';

type Row = Record<string, any>;

const CHUNK = 200;
const FILTER_DEBOUNCE = 300;
const REALTIME_THROTTLE_MS = 1200;

// only these tables can create
const CAN_CREATE = new Set(['jobs', 'courses']);

/* ------------------------------ Date helpers ------------------------------ */

type DateFilter = { gt?: string; gte?: string; lt?: string; lte?: string };

const pad = (n: number) => String(n).padStart(2, '0');
const toISODate = (y: number, m: number, d: number) =>
  `${y}-${pad(m)}-${pad(d)}T00:00:00Z`;
const addDaysISO = (isoStart: string, days: number) =>
  new Date(new Date(isoStart).getTime() + days * 86400000).toISOString();

function parseYyyyMmDdDigits(s: string): { y: number; m: number; d: number } | null {
  if (!/^\d{8}$/.test(s)) return null;
  const y = Number(s.slice(0, 4));
  const m = Number(s.slice(4, 6));
  const d = Number(s.slice(6, 8));
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  return { y, m, d };
}

function parseMonthDigits(s: string): { y: number; m: number } | null {
  if (/^\d{6}$/.test(s)) {
    const y = Number(s.slice(0, 4));
    const m = Number(s.slice(4, 6));
    if (m >= 1 && m <= 12) return { y, m };
  }
  if (/^\d{4}-\d{2}$/.test(s)) {
    const [y, m] = s.split('-').map(Number);
    if (m >= 1 && m <= 12) return { y, m };
  }
  return null;
}

function nextMonthStartISO(y: number, m: number): string {
  const ny = m === 12 ? y + 1 : y;
  const nm = m === 12 ? 1 : m + 1;
  return toISODate(ny, nm, 1);
}

function parseDateFilter(inputRaw: string): DateFilter | null {
  const input = inputRaw.trim();

  // Range: YYYY-MM-DD..YYYY-MM-DD
  const range = input.match(/^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$/);
  if (range) {
    const start = `${range[1]}T00:00:00Z`;
    const endNext = addDaysISO(`${range[2]}T00:00:00Z`, 1); // inclusive end → lt next day
    return { gte: start, lt: endNext };
  }

  // Operators: >=, >, <=, <
  // Simplified to only match YYYY-MM-DD to guide user input
  const op = input.match(/^(>=|>|<=|<)\s*(\d{4}-\d{2}-\d{2})$/);
  if (op) {
    const isoStart = `${op[2]}T00:00:00Z`;
    const nextDay = addDaysISO(isoStart, 1);
    switch (op[1]) {
      case '>=': return { gte: isoStart };
      case '>':  return { gt: nextDay };      // strictly after the whole day
      case '<=': return { lt: nextDay };      // up to end-of-day
      case '<':  return { lt: isoStart };     // strictly before that day
    }
  }

  // Single full date: YYYY-MM-DD or YYYY/MM/DD
  if (/^(\d{4}[-\/]\d{2}[-\/]\d{2})$/.test(input)) {
    const standardInput = input.replace(/\//g, '-');
    const start = `${standardInput}T00:00:00Z`;
    const next = addDaysISO(start, 1);
    return { gte: start, lt: next };
  }

  // 8-digit yyyymmdd
  const d8 = parseYyyyMmDdDigits(input);
  if (d8) {
    const start = toISODate(d8.y, d8.m, d8.d);
    const next = addDaysISO(start, 1);
    return { gte: start, lt: next };
  }

  // Month: YYYY-MM or yyyymm
  const m6 = parseMonthDigits(input);
  if (m6) {
    const start = toISODate(m6.y, m6.m, 1);
    const nextM = nextMonthStartISO(m6.y, m6.m);
    return { gte: start, lt: nextM };
  }

  // Year: YYYY
  if (/^\d{4}$/.test(input)) {
    const y = Number(input);
    const start = toISODate(y, 1, 1);
    const nextY = toISODate(y + 1, 1, 1);
    return { gte: start, lt: nextY };
  }

  // Unknown pattern → ignore (don’t break query)
  return null;
}

/* --------------------------------- Component -------------------------------- */

interface CRUDTableViewerProps {
  tableName: string;
  columns: string[];
}

export default function CRUDTableViewer({ tableName, columns }: CRUDTableViewerProps) {
  // data + loading
  const [data, setData] = useState<Row[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // filters
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [debouncedFilters, setDebouncedFilters] = useState<Record<string, string>>({});

  // keyset
  const cursorRef = useRef<string | number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const loaderRef = useRef<HTMLDivElement | null>(null);

  // seen PKs
  const seenPk = useRef<Set<string | number>>(new Set());

  // in-flight cancel
  const fetchAbortRef = useRef<AbortController | null>(null);

  // edit state
  const [editingRow, setEditingRow] = useState<Row | null>(null);
  const [editingKey, setEditingKey] = useState<string | number | null>(null);

  // create / view / delete
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewRow, setViewRow] = useState<Row | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteId, setDeleteId] = useState<any>(null);
  const [deletePreview, setDeletePreview] = useState<string>('');

  /* ---------- PKs ---------- */
  const PK_BY_TABLE: Record<string, string> = {
    courses: 'course_id',
    jobs: 'job_id',
    job_skills: 'job_skill_id',
    course_skills: 'course_skill_id',
    course_alignment_scores_clean: 'course_alignment_score_clean_id',
  };
  const pkCol = PK_BY_TABLE[tableName] ?? 'id';

  const canCreate = CAN_CREATE.has(tableName);

  /* ---------- Columns ---------- */
  const readonlyCols = useMemo(
    () => new Set<string>(['id', pkCol, 'created_at', 'updated_at']),
    [pkCol]
  );

  const isHidden = useCallback((c: string) => c === 'id' || c === pkCol, [pkCol]);

  const VISIBLE_COLUMNS = useMemo(
    () => (columns ?? []).filter((c) => !isHidden(c)),
    [columns, isHidden]
  );

  const createCols = useMemo(
    () => (columns ?? []).filter((c) => !readonlyCols.has(c) && !isHidden(c)),
    [columns, readonlyCols, isHidden]
  );

  const selectCols = useMemo(() => [pkCol, ...VISIBLE_COLUMNS], [pkCol, VISIBLE_COLUMNS]);

  /* ---------- Date & formatting ---------- */
  const DATE_COLUMNS = useMemo(
    () =>
      new Set<string>([
        'created_at',
        'updated_at',
        'scraped_at',
        'date_extracted_jobs',
        'date_extracted_course',
        'calculated_at',
      ]),
    []
  );

  // 🎯 REVISED: Standardized display format YYYY/MM/DD, HH:MM:SS AM/PM
  const formatDate = (v: any) => {
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    
    // Get date parts (MM/DD/YYYY)
    const parts = d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).split('/');
    
    // Re-arrange to YYYY/MM/DD
    const datePart = `${parts[2]}/${parts[0]}/${parts[1]}`;

    // Standardized time part: HH:MM:SS AM/PM
    const timePart = d.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });
    
    return `${datePart}, ${timePart}`;
  };

  const formatDateOnly = (v: any) => {
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    // Format to YYYY-MM-DD
    return d.toISOString().split('T')[0];
  };

  // Define columns that should use the date-only format
  const DATE_ONLY_COLUMNS = useMemo(
    () => new Set<string>(['scraped_at']),
    []
  );

  const ARRAY_COLUMNS = useMemo(
    () => new Set<string>(['skills_taught', 'skills_in_market']),
    []
  );

  const MAX_CELL_CHARS = 30;
  const clip = (v: any, n = MAX_CELL_CHARS) => {
    const s = String(v ?? '');
    return s.length > n ? `${s.slice(0, n - 1)}…` : s;
    };

  /* ---------- Debounce filters ---------- */
  useEffect(() => {
    const t = setTimeout(() => setDebouncedFilters(filters), FILTER_DEBOUNCE);
    return () => clearTimeout(t);
  }, [filters]);

  /* ================== Fetch: keyset pagination ================== */

  const buildQuery = useCallback(() => {
    let q = supabase
      .from(tableName)
      .select(selectCols.join(','))
      .order(pkCol, { ascending: true });

    if (cursorRef.current != null) {
      q = q.gt(pkCol, cursorRef.current);
    }

    // apply filters
    for (const [col, rawVal] of Object.entries(debouncedFilters)) {
      const val = (rawVal ?? '').trim();
      if (!val) continue;

      if (DATE_COLUMNS.has(col)) {
        const f = parseDateFilter(val);
        if (!f) {
          // ignore unrecognized date pattern to avoid PostgREST type errors
          continue;
        }
        if (f.gte) q = q.gte(col, f.gte);
        if (f.gt) q = q.gt(col, f.gt);
        if (f.lte) q = q.lte(col, f.lte);
        if (f.lt) q = q.lt(col, f.lt);
      } else {
        q = q.ilike(col, `%${val}%`);
      }
    }

    return q.limit(CHUNK);
  }, [tableName, selectCols, debouncedFilters, pkCol, DATE_COLUMNS]);

  const loadMore = useCallback(async () => {
    if (isLoading || !hasMore) return;

    fetchAbortRef.current?.abort();
    const ctrl = new AbortController();
    fetchAbortRef.current = ctrl;

    setIsLoading(true);
    setErrorMsg(null);

    try {
      const q = buildQuery();
      // @ts-ignore: supabase-js v2 supports AbortSignal via .abortSignal()
      const { data: rows, error } = await (q.abortSignal?.(ctrl.signal) ?? q);

      if (ctrl.signal.aborted) return;

      if (error) {
        setErrorMsg(error.message);
        setHasMore(false);
        return;
      }

      const newRows = (rows ?? []) as Row[];
      if (newRows.length > 0) {
        const pkKey = pkCol as keyof Row;
        const last = newRows[newRows.length - 1]?.[pkKey] as string | number | null;
        cursorRef.current = last ?? cursorRef.current;

        const merged: Row[] = [];
        for (const r of newRows) {
          const id = r[pkKey] as string | number;
          if (!seenPk.current.has(id)) {
            seenPk.current.add(id);
            merged.push(r);
          }
        }

        setData((prev) => [...prev, ...merged]);
        setHasMore(newRows.length === CHUNK);
      } else {
        setHasMore(false);
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setErrorMsg(err?.message ?? String(err));
        setHasMore(false);
      }
    } finally {
      setIsLoading(false);
    }
  }, [buildQuery, hasMore, isLoading, pkCol]);

  const resetAndReload = useCallback(async () => {
    fetchAbortRef.current?.abort();
    cursorRef.current = null;
    seenPk.current = new Set();
    setData([]);
    setHasMore(true);
    await loadMore();
  }, [loadMore]);

  useEffect(() => {
    resetAndReload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableName, selectCols.join(','), JSON.stringify(debouncedFilters)]);

  /* ---------- Infinite scroll sentinel ---------- */
  useEffect(() => {
    if (!loaderRef.current) return;
    const el = loaderRef.current;

    const obs = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (first.isIntersecting) loadMore();
      },
      { root: null, rootMargin: '600px', threshold: 0 }
    );

    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  /* ---------- Realtime soft refresh ---------- */
  useEffect(() => {
    let scheduled = false;
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      setTimeout(async () => {
        invalidateDbCache(tableName);
        cursorRef.current = null;
        seenPk.current = new Set();
        setData([]);
        setHasMore(true);
        await loadMore();
        scheduled = false;
      }, REALTIME_THROTTLE_MS);
    };

    const channel = supabase
      .channel(`${tableName}-changes`)
      .on('postgres_changes', { event: '*', schema: 'public', table: tableName }, schedule)
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [tableName, loadMore]);

  /* ================== Edit / CRUD ================== */

  const getRowKey = (row: Row) => row?.[pkCol as keyof Row] ?? null;

  const startEdit = (row: Row) => {
    setEditingRow({ ...(row ?? {}) });
    setEditingKey(getRowKey(row));
  };

  const cancelEdit = () => {
    setEditingRow(null);
    setEditingKey(null);
  };

  const handleSave = async () => {
    if (!editingRow) return;
    const idVal = (editingRow[pkCol as keyof Row] ?? editingKey) as string | number | null;

    const { [pkCol]: _omit, ...payload } = editingRow;
    const { error } = await supabase.from(tableName).update(payload).eq(pkCol, idVal);
    if (error) {
      setErrorMsg(error.message);
      return;
    }
    cancelEdit();
    await resetAndReload();
  };

  // Delete
  const openDelete = (row: Row) => {
    const idVal = row?.[pkCol as keyof Row];
    if (!idVal) return;
    setDeleteId(idVal);
    const previewCols = VISIBLE_COLUMNS.slice(0, 3);
    const preview = previewCols
      .map((c) => `${c.replace(/_/g, ' ')}: ${clip(row[c], 30) || '—'}`)
      .join(' • ');
    setDeletePreview(preview);
    setShowDeleteModal(true);
  };

  const confirmDelete = async () => {
    if (!deleteId) return;
    const { error } = await supabase.from(tableName).delete().eq(pkCol, deleteId);
    if (error) {
      setErrorMsg(error.message);
      return;
    }
    setShowDeleteModal(false);
    setDeleteId(null);
    await resetAndReload();
  };
  const cancelDelete = () => {
    setShowDeleteModal(false);
    setDeleteId(null);
  };

  /* ----------------------------------- UI ----------------------------------- */

  return (
    <div className="btn_border_silver">
      <div className="card_background rounded p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text_defaultColor text-xl font-bold capitalize">
            {tableName.replace(/_/g, ' ')}
          </h3>

          <div className="flex items-center gap-3">
            <UpdateBadge tableName={tableName} />
            <button
              onClick={() => resetAndReload()}
              className="rounded border px-3 py-2 text-sm hover:bg-gray-100"
              title="Refresh"
            >
              Refresh
            </button>

            {CAN_CREATE.has(tableName) && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="rounded bg-green-700 px-3 py-2 text-white transition hover:bg-green-600"
              >
                + Add New
              </button>
            )}
          </div>
        </div>

        {errorMsg && (
          <div className="mb-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {errorMsg}
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              {/* Filters */}
              <tr>
                {VISIBLE_COLUMNS.map((col) => (
                  <th key={col} className="px-2 py-2">
                    <input
                      placeholder={DATE_COLUMNS.has(col) ? 'YYYY-MM-DD, YYYY-MM, or YYYY' : col}
                      className="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs"
                      value={filters[col] ?? ''}
                      onChange={(e) =>
                        setFilters((prev) => ({ ...prev, [col]: e.target.value }))
                      }
                    />
                  </th>
                ))}
                <th className="px-2 py-2 text-sm text_secondaryColor">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      className="rounded border px-2 py-1 text-[11px]"
                      onClick={() => setFilters({})}
                      title="Clear filters"
                    >
                      Clear
                    </button>
                  </div>
                </th>
              </tr>

              {/* Headers */}
              <tr className="border-b border-gray-200 bg-gray-50">
                {VISIBLE_COLUMNS.map((col) => (
                  <th key={col} className="px-2 py-2 text-left capitalize text_secondaryColor">
                    {col.replace(/_/g, ' ')}
                  </th>
                ))}
                <th className="px-2 py-2"></th>
              </tr>
            </thead>

            <tbody>
              {data.map((row, i) => {
                const key = (getRowKey(row) ?? i) as string | number;
                const isEditing = editingKey != null && key === editingKey;

                return (
                  <tr
                    key={key}
                    className={`border-b border-gray-200 transition-colors ${
                      i % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                    } hover:bg-gray-100`}
                  >
                    {VISIBLE_COLUMNS.map((col) => {
                      if (isEditing) {
                        const value = String(editingRow?.[col] ?? '');
                        return (
                          <td key={col} className="px-2 py-2 text_defaultColor">
                            <input
                              className="w-full rounded border border-gray-300 px-2 py-1"
                              value={value}
                              onChange={(e) =>
                                setEditingRow((prev) => ({
                                  ...(prev ?? {}),
                                  [col]: e.target.value,
                                }))
                              }
                            />
                          </td>
                        );
                      }

                      let raw = row[col];
                      let displayValue = raw;

                      // 1. Handle Date Formatting
                      if (DATE_COLUMNS.has(col) && raw) {
                        const formatter = DATE_ONLY_COLUMNS.has(col) 
                          ? formatDateOnly // YYYY-MM-DD for scraped_at
                          : formatDate;   // YYYY/MM/DD, HH:MM:SS AM/PM for others
                        displayValue = clip(formatter(raw));
                      } 
                      // 2. Handle Array Bracket Removal
                      else if (ARRAY_COLUMNS.has(col) && typeof raw === 'string') {
                        let s = raw.trim();
                        if (s.startsWith('[') && s.endsWith(']')) {
                          s = s.slice(1, -1);
                        }
                        displayValue = clip(s);
                      }
                      // 3. Handle standard text/other columns
                      else {
                        displayValue = clip(raw);
                      }
                      
                      return (
                        <td key={col} className="px-2 py-2 text_defaultColor" title={String(raw ?? '')}>
                          <span className="block max-w-[32rem] truncate">{displayValue ?? '—'}</span>
                        </td>
                      );
                    })}

                    <td className="px-2 py-2">
                      {isEditing ? (
                        <div className="flex items-center justify-end gap-2">
                          <button
                            className="rounded bg-green-600 px-2 py-1 text-white hover:bg-green-500"
                            onClick={handleSave}
                            title="Save"
                          >
                            Save
                          </button>
                          <button
                            className="rounded bg-gray-400 px-2 py-1 text-white hover:bg-gray-300"
                            onClick={cancelEdit}
                            title="Cancel"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-end gap-2">
                          <button
                            className="rounded p-1 hover:bg-gray-200"
                            onClick={() => setViewRow(row)}
                            title="View"
                          >
                            <RiEyeLine className="h-5 w-5 text-[var(--brand-teal,#025864)]" />
                          </button>
                          <button
                            className="rounded p-1 hover:bg-gray-200"
                            onClick={() => startEdit(row)}
                            title="Edit"
                          >
                            <RiEdit2Line className="h-5 w-5 text-blue-600" />
                          </button>
                          <button
                            className="rounded p-1 hover:bg-gray-200"
                            onClick={() => openDelete(row)}
                            title="Delete"
                          >
                            <RiDeleteBinLine className="h-5 w-5 text-red-600" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}

              {/* Infinite scroll sentinel */}
              <tr>
                <td colSpan={VISIBLE_COLUMNS.length + 1}>
                  <div ref={loaderRef} className="py-3 text-center text-xs text-gray-500">
                    {isLoading
                      ? 'Loading…'
                      : hasMore
                      ? 'Scroll to load more'
                      : data.length === 0
                      ? 'No rows'
                      : 'End of results'}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Modals */}
        {canCreate && showCreateModal && (
          <AddRowModal
            tableName={tableName}
            columns={createCols}
            onClose={() => setShowCreateModal(false)}
            onCreated={resetAndReload}
          />
        )}

        {viewRow && (
          <ViewRowModal
            tableName={tableName}
            row={viewRow}
            visibleColumns={VISIBLE_COLUMNS}
            onClose={() => setViewRow(null)}
          />
        )}

        {showDeleteModal && (
          <DeleteConfirmModal
            onCancel={cancelDelete}
            onConfirm={confirmDelete}
            tableName={tableName}
            preview={deletePreview}
          />
        )}
      </div>
    </div>
  );
}

/* ---------------- Delete confirm modal ---------------- */

function DeleteConfirmModal({
  onCancel,
  onConfirm,
  tableName,
  preview,
}: {
  onCancel: () => void;
  onConfirm: () => void;
  tableName: string;
  preview?: string;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onMouseDown={onCancel}
      onClick={onCancel}
    >
      <div
        className="w-[92vw] max-w-md rounded-xl bg-white shadow-2xl border border-red-200"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 p-4">
          <div className="mt-0.5 rounded-full bg-red-100 p-2">
            <RiAlertLine className="h-5 w-5 text-red-600" />
          </div>
          <div className="flex-1">
            <h4 className="text-base font-semibold text-red-700">
              Delete row from “{tableName.replace(/_/g, ' ')}”?
            </h4>
            {preview ? (
              <p className="mt-1 text-sm text-gray-700">
                You’re about to permanently delete:
                <br />
                <span className="font-medium">{preview}</span>
              </p>
            ) : (
              <p className="mt-1 text-sm text-gray-700">
                This action cannot be undone. The row will be permanently removed.
              </p>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t bg-gray-50 p-3">
          <button
            className="rounded px-3 py-2 bg-gray-200 text-gray-800 hover:bg-gray-300"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="rounded px-3 py-2 bg-red-600 text-white hover:bg-red-500"
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}