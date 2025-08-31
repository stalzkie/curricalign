'use client';

import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { supabase } from '@/lib/supabaseClients';
import { invalidateDbCache } from '@/lib/databaseService';
import { RiEyeLine, RiEdit2Line, RiDeleteBinLine, RiAlertLine } from 'react-icons/ri';
import AddRowModal from './AddRowModal';
import ViewRowModal from './ViewRowModal';
import UpdateBadge from '../dashboard/UpdateBadge';

/* ================== Types & Config ================== */

type Row = Record<string, any>;

const CHUNK = 200;             // rows per fetch (infinite scroll)
const FILTER_DEBOUNCE = 300;   // ms
const REALTIME_THROTTLE_MS = 1200;

// Only these tables can create new rows
const CAN_CREATE = new Set(['jobs', 'courses']);

interface CRUDTableViewerProps {
  tableName: string;
  columns: string[];
}

/* ================== Component ================== */

export default function CRUDTableViewer({ tableName, columns }: CRUDTableViewerProps) {
  // Data + loading state
  const [data, setData] = useState<Row[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Filters (debounced)
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [debouncedFilters, setDebouncedFilters] = useState<Record<string, string>>({});

  // Infinite scroll (keyset)
  const cursorRef = useRef<string | number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const loaderRef = useRef<HTMLDivElement | null>(null);

  // Seen PKs to de-dupe (important with realtime + reset)
  const seenPk = useRef<Set<string | number>>(new Set());

  // In-flight fetch cancellation
  const fetchAbortRef = useRef<AbortController | null>(null);

  // Edit state
  const [editingRow, setEditingRow] = useState<Row | null>(null);
  const [editingKey, setEditingKey] = useState<string | number | null>(null);

  // Create / View modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewRow, setViewRow] = useState<Row | null>(null);

  // Delete modal
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteId, setDeleteId] = useState<any>(null);
  const [deletePreview, setDeletePreview] = useState<string>('');

  /* ---------- Primary Key by table ---------- */
  const PK_BY_TABLE: Record<string, string> = {
    courses: 'course_id',
    jobs: 'job_id',
    job_skills: 'job_skill_id',
    course_skills: 'course_skill_id',
    course_alignment_scores_clean: 'course_alignment_score_clean_id',
  };
  const pkCol = PK_BY_TABLE[tableName] ?? 'id';

  // Create permission for current table
  const canCreate = CAN_CREATE.has(tableName);

  /* ---------- Columns config ---------- */
  const readonlyCols = useMemo(
    () => new Set<string>(['id', pkCol, 'created_at', 'updated_at']),
    [pkCol]
  );

  const isHidden = useCallback((col: string) => col === 'id' || col === pkCol, [pkCol]);

  const VISIBLE_COLUMNS = useMemo(
    () => (columns ?? []).filter((c) => !isHidden(c)),
    [columns, isHidden]
  );

  const createCols = useMemo(
    () => (columns ?? []).filter((c) => !readonlyCols.has(c) && !isHidden(c)),
    [columns, readonlyCols, isHidden]
  );

  const selectCols = useMemo(() => [pkCol, ...VISIBLE_COLUMNS], [pkCol, VISIBLE_COLUMNS]);

  /* ---------- Date + truncation helpers ---------- */
  const DATE_COLUMNS = new Set<string>([
    'created_at',
    'updated_at',
    'scraped_at',
    'date_extracted_jobs',
    'date_extracted_course',
    'calculated_at',
  ]);

  const formatDate = (v: any) => {
    const d = new Date(v);
    if (isNaN(d.getTime())) return v;
    return d.toLocaleString();
  };

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

  const hasFilters = useMemo(
    () => Object.values(debouncedFilters).some((v) => v?.trim()),
    [debouncedFilters]
  );

  /* ================== Fetch: keyset pagination ================== */

  const buildQuery = useCallback(() => {
    let q = supabase
      .from(tableName)
      .select(selectCols.join(','))
      .order(pkCol, { ascending: true });

    // keyset cursor
    if (cursorRef.current != null) {
      q = q.gt(pkCol, cursorRef.current);
    }

    // server-side filters (ilike for string-ish columns)
    for (const [col, val] of Object.entries(debouncedFilters)) {
      if (val?.trim()) q = q.ilike(col, `%${val.trim()}%`);
    }

    q = q.limit(CHUNK);
    return q;
  }, [tableName, selectCols, debouncedFilters, pkCol]);

  const loadMore = useCallback(async () => {
    if (isLoading || !hasMore) return;

    // Cancel any previous fetch (rare but safe)
    fetchAbortRef.current?.abort();
    const ctrl = new AbortController();
    fetchAbortRef.current = ctrl;

    setIsLoading(true);
    setErrorMsg(null);

    try {
      const q = buildQuery();
      // @ts-ignore – supabase-js v2 supports AbortSignal via .abortSignal()
      const { data: rows, error } = await (q.abortSignal?.(ctrl.signal) ?? q);

      if (ctrl.signal.aborted) return;

      if (error) {
        setErrorMsg(error.message);
        return;
      }

      const newRows = (rows ?? []) as Row[];
      if (newRows.length > 0) {
        // advance cursor to last PK in this chunk
        const pkKey = pkCol as keyof Row;
        const last = newRows[newRows.length - 1]?.[pkKey] as string | number | null;
        cursorRef.current = last ?? cursorRef.current;

        // de-dupe using a Set of seen PKs
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
      if (err?.name !== 'AbortError') setErrorMsg(err?.message ?? String(err));
    } finally {
      setIsLoading(false);
    }
  }, [buildQuery, hasMore, isLoading, pkCol]);

  // Reset & initial load when deps change
  const resetAndReload = useCallback(async () => {
    // cancel any in-flight
    fetchAbortRef.current?.abort();

    // reset cursors and caches
    cursorRef.current = null;
    seenPk.current = new Set();
    setData([]);
    setHasMore(true);

    // initial page
    await loadMore();
  }, [loadMore]);

  useEffect(() => {
    resetAndReload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableName, selectCols.join(','), JSON.stringify(debouncedFilters)]);

  /* ---------- Infinite scroll observer ---------- */
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

  /* ---------- Realtime (throttled soft refresh) ---------- */
  useEffect(() => {
    let scheduled = false;
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      setTimeout(async () => {
        invalidateDbCache(tableName); // keeps UpdateBadge accurate
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

  /* ================== UI ================== */

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

            {canCreate && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="rounded bg-[var(--brand-teal,#025864)] px-3 py-2 text-white transition hover:opacity-90"
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
              {/* Filters (debounced) */}
              <tr>
                {VISIBLE_COLUMNS.map((col) => (
                  <th key={col} className="px-2 py-2">
                    <input
                      placeholder={col}
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

                      const raw = row[col];
                      const formatted = DATE_COLUMNS.has(col) && raw ? formatDate(raw) : raw;
                      const display = clip(formatted);

                      return (
                        <td
                          key={col}
                          className="px-2 py-2 text_defaultColor"
                          title={String(formatted ?? '')}
                        >
                          <span className="block max-w-[32rem] truncate">{display ?? '—'}</span>
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

              {/* Infinite scroll sentinel row */}
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

/* ---------- Local modal component for delete confirmation (notification style) ---------- */

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
