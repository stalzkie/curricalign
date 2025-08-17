// src/components/database/TableViewer.tsx
'use client';

import { useEffect, useMemo, useState, useCallback } from 'react';
import { supabase } from '@/lib/supabaseClients';
import { RiEyeLine, RiEdit2Line, RiDeleteBinLine, RiCloseLine } from 'react-icons/ri';

interface CRUDTableViewerProps {
  tableName: string;
  columns: string[];
}

export default function CRUDTableViewer({ tableName, columns }: CRUDTableViewerProps) {
  const [data, setData] = useState<any[]>([]);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [editingRow, setEditingRow] = useState<Record<string, any> | null>(null);
  const [editingKey, setEditingKey] = useState<string | number | null>(null);
  const [newRow, setNewRow] = useState<Record<string, any>>({});
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewRow, setViewRow] = useState<Record<string, any> | null>(null);

  // columns config
  const readonlyCols = new Set(['id', 'created_at', 'updated_at']);
  const VISIBLE_COLUMNS = useMemo(() => columns.filter((c) => c !== 'id'), [columns]);
  const VIEW_COLUMNS = useMemo(() => columns.filter((c) => c !== 'id'), [columns]); // hide id in View modal
  const createCols = useMemo(() => columns.filter((c) => !readonlyCols.has(c)), [columns]);

  const MAX_CHARS = 80;
  const truncate = (v: any, n = MAX_CHARS) => {
    const s = String(v ?? '');
    return s.length > n ? `${s.slice(0, n)}…` : s;
  };

  // lock page scroll when any modal is open
  const anyModalOpen = showCreateModal || !!viewRow;
  useEffect(() => {
    if (anyModalOpen) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = prev;
      };
    }
  }, [anyModalOpen]);

  /** 🔄 Fetch */
  const fetchData = useCallback(async () => {
    const { data: rows, error } = await supabase.from(tableName).select('*');
    if (error) {
      console.error(`[${tableName}] Fetch error:`, error);
      setData([]);
    } else {
      setData(rows ?? []);
    }
  }, [tableName]);

  useEffect(() => {
    fetchData();
    const channel = supabase
      .channel(`${tableName}-changes`)
      .on('postgres_changes', { event: '*', schema: 'public', table: tableName }, () => fetchData())
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [tableName, fetchData]);

  /** ✍️ Edit helpers */
  const getRowKey = (row: any) => row?.id ?? row?.pk ?? row?.key;
  const startEdit = (row: any) => {
    setEditingRow({ ...(row ?? {}) });
    setEditingKey(getRowKey(row) ?? null);
  };
  const cancelEdit = () => {
    setEditingRow(null);
    setEditingKey(null);
  };

  /** 💾 Save */
  const handleSave = async () => {
    if (!editingRow) return;
    const id = editingRow.id ?? editingKey;
    if (id == null) return console.error('Save aborted: no id/primary key on editingRow.');
    const { id: _omit, ...payload } = editingRow;
    const { error } = await supabase.from(tableName).update(payload).eq('id', id);
    if (error) return console.error(`[${tableName}] Update error:`, error);
    cancelEdit();
    fetchData();
  };

  /** ➕ Create */
  const handleCreate = async () => {
    const payload: Record<string, any> = {};
    for (const c of createCols) payload[c] = newRow[c] ?? null;
    const { error } = await supabase.from(tableName).insert([payload]);
    if (error) return console.error(`[${tableName}] Insert error:`, error);
    setNewRow({});
    setShowCreateModal(false);
    fetchData();
  };

  /** ❌ Delete */
  const handleDelete = async (id: any) => {
    const { error } = await supabase.from(tableName).delete().eq('id', id);
    if (error) return console.error(`[${tableName}] Delete error:`, error);
    fetchData();
  };

  /** 🔍 Filters (only visible cols) */
  const filtered = useMemo(
    () =>
      data
        .filter(Boolean)
        .filter((row) =>
          VISIBLE_COLUMNS.every(
            (col) =>
              (filters[col] ?? '') === '' ||
              String(row?.[col] ?? '').toLowerCase().includes((filters[col] ?? '').toLowerCase()),
          ),
        ),
    [data, filters, VISIBLE_COLUMNS],
  );

  /** Overlay wrapper (blur + dim + click outside to close) */
  const ModalOverlay: React.FC<{ onClose: () => void; children: React.ReactNode }> = ({
    onClose,
    children,
  }) => (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="max-h-[85vh] w-[92vw] max-w-2xl overflow-auto rounded-xl bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );

  return (
    <div className="btn_border_silver">
      <div className="card_background rounded p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text_defaultColor text-xl font-bold capitalize">{tableName.replace(/_/g, ' ')}</h3>
          <button
            onClick={() => setShowCreateModal(true)}
            className="rounded bg-[var(--brand-teal,#025864)] px-3 py-2 text-white transition hover:opacity-90"
          >
            + Add New
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              {/* Filters row (no ID) */}
              <tr>
                {VISIBLE_COLUMNS.map((col) => (
                  <th key={col} className="px-2 py-2">
                    <input
                      placeholder={col}
                      className="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs"
                      value={filters[col] ?? ''}
                      onChange={(e) => setFilters((prev) => ({ ...prev, [col]: e.target.value }))}
                    />
                  </th>
                ))}
                <th className="px-2 py-2 text-sm text_secondaryColor">Actions</th>
              </tr>
              {/* Column names (no ID) */}
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
              {filtered.map((row, i) => {
                const key = getRowKey(row) ?? i;
                const isEditing = editingKey != null && key === editingKey;

                return (
                  <tr
                    key={key}
                    className={`border-b border-gray-200 transition-colors ${
                      i % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                    } hover:bg-gray-100`}
                  >
                    {VISIBLE_COLUMNS.map((col) => {
                      const readOnly = readonlyCols.has(col);

                      if (isEditing) {
                        const value = String(editingRow?.[col] ?? '');
                        return (
                          <td key={col} className="px-2 py-2 text_defaultColor">
                            <input
                              className="w-full rounded border border-gray-300 px-2 py-1"
                              value={value}
                              onChange={(e) =>
                                setEditingRow((prev) => ({ ...(prev ?? {}), [col]: e.target.value }))
                              }
                              readOnly={readOnly}
                            />
                          </td>
                        );
                      }

                      const raw = row?.[col];
                      const display = truncate(raw);
                      return (
                        <td key={col} className="px-2 py-2 text_defaultColor" title={String(raw ?? '')}>
                          {display || '—'}
                        </td>
                      );
                    })}

                    <td className="space-x-3 px-2 py-2 text-right">
                      {isEditing ? (
                        <>
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
                        </>
                      ) : (
                        <div className="flex items-center justify-end gap-3">
                          <button
                            className="rounded p-1 hover:bg-gray-200"
                            onClick={() => setViewRow(row)}
                            title="View"
                          >
                            <RiEyeLine className="h-5 w-5 text-gray-700" />
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
                            onClick={() => handleDelete(row?.id)}
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
            </tbody>
          </table>
        </div>

        {/* Add New Modal (with blur + dim, scroll lock) */}
        {showCreateModal && (
          <ModalOverlay onClose={() => setShowCreateModal(false)}>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-lg font-bold">Add New {tableName}</h3>
              <button onClick={() => setShowCreateModal(false)} className="rounded p-1 hover:bg-gray-100">
                <RiCloseLine className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-3">
              {createCols.map((col) => (
                <div key={col}>
                  <label className="block text-sm font-medium text-gray-700">{col.replace(/_/g, ' ')}</label>
                  <input
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
                    value={String(newRow[col] ?? '')}
                    onChange={(e) => setNewRow((prev) => ({ ...(prev ?? {}), [col]: e.target.value }))}
                  />
                </div>
              ))}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                className="rounded bg-gray-400 px-3 py-2 text-white hover:bg-gray-300"
                onClick={() => setShowCreateModal(false)}
              >
                Cancel
              </button>
              <button
                className="rounded bg-[var(--brand-teal,#025864)] px-3 py-2 text-white hover:opacity-90"
                onClick={handleCreate}
              >
                Create
              </button>
            </div>
          </ModalOverlay>
        )}

        {/* View Modal (no id, blur + dim, scroll lock) */}
        {viewRow && (
          <ModalOverlay onClose={() => setViewRow(null)}>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-bold">Row details</h3>
              <button onClick={() => setViewRow(null)} className="rounded p-1 hover:bg-gray-100">
                <RiCloseLine className="h-5 w-5" />
              </button>
            </div>

            <div className="grid max-h-[65vh] grid-cols-1 gap-4 overflow-auto md:grid-cols-2">
              {VIEW_COLUMNS.map((col) => (
                <div key={col} className="rounded border p-3">
                  <div className="mb-1 text-xs text-gray-500">{col.replace(/_/g, ' ')}</div>
                  <div className="whitespace-pre-wrap break-words text-sm">
                    {String(viewRow[col] ?? '—')}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex justify-end">
              <button
                className="rounded bg-[var(--brand-teal,#025864)] px-3 py-2 text-white hover:opacity-90"
                onClick={() => setViewRow(null)}
              >
                Close
              </button>
            </div>
          </ModalOverlay>
        )}
      </div>
    </div>
  );
}
