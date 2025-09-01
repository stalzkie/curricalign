'use client';

import { supabase } from '@/lib/supabaseClients';
import { useMemo, useState } from 'react';

interface AddRowModalProps {
  tableName: string;          // 'jobs' | 'courses' (only these are allowed)
  columns: string[];          // fields to render (from the grid)
  onClose: () => void;
  onCreated: () => void;      // parent will refetch
}

const CAN_CREATE = new Set(['jobs', 'courses']);

// columns we never render as inputs
const READONLY_ALWAYS = new Set(['id', 'created_at', 'updated_at', 'scraped_at']);
// table-specific primary keys we also hide
const PK_BY_TABLE: Record<string, string> = {
  jobs: 'job_id',
  courses: 'course_id',
};

export default function AddRowModal({
  tableName,
  columns,
  onClose,
  onCreated,
}: AddRowModalProps) {
  // hard guard: if someone accidentally renders this on a non-allowed table, render nothing
  if (!CAN_CREATE.has(tableName)) return null;

  const [newRow, setNewRow] = useState<Record<string, any>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const pkCol = PK_BY_TABLE[tableName] ?? 'id';

  // Only show editable, non-readonly fields
  const formColumns = useMemo(() => {
    const blacklist = new Set<string>([...READONLY_ALWAYS, pkCol]);
    // Deduplicate + filter
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of (columns ?? [])) {
      const k = String(c);
      if (!k) continue;
      if (blacklist.has(k)) continue;
      if (!seen.has(k)) {
        seen.add(k);
        out.push(k);
      }
    }
    return out;
  }, [columns, pkCol]);

  // Build payload only with non-empty values
  const buildPayload = () => {
    const payload: Record<string, any> = {};
    for (const c of formColumns) {
      const v = newRow[c];
      if (v !== undefined && v !== null && !(typeof v === 'string' && v.trim() === '')) {
        payload[c] = v;
      }
    }
    return payload;
  };

  const handleCreate = async () => {
    setIsSaving(true);
    setErrorMsg(null);
    try {
      const payload = buildPayload();

      if (Object.keys(payload).length === 0) {
        setErrorMsg('Please fill at least one field.');
        setIsSaving(false);
        return;
      }

      // Supabase v2: no .select() => no extra return round-trip
      const { error } = await supabase.from(tableName).insert([payload]);
      if (error) {
        const hint = /row-level security/i.test(error.message)
          ? ' (RLS may be blocking inserts. Ensure an INSERT policy exists for your role.)'
          : '';
        setErrorMsg(`${error.message}${hint}`);
        setIsSaving(false);
        return;
      }

      setNewRow({});
      onClose();
      onCreated();
    } catch (err: any) {
      setErrorMsg(err?.message ?? String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const renderInput = (col: string) => {
    // keep it simple: plain text input; customize placeholders for common fields
    const placeholder =
      col === 'title' || col === 'course_title'
        ? 'e.g. Introduction to Data Science'
        : col === 'company'
        ? 'e.g. ACME Corp'
        : col === 'course_code'
        ? 'e.g. CS101'
        : undefined;

    return (
      <input
        className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
        value={newRow[col] ?? ''}
        onChange={(e) =>
          setNewRow((prev) => ({ ...(prev ?? {}), [col]: e.target.value }))
        }
        placeholder={placeholder}
      />
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="max-h-[85vh] w-[92vw] max-w-2xl bg-white p-6 rounded-xl shadow-2xl overflow-auto">
        <h3 className="text-lg font-bold mb-4">
          Add New {tableName.replace(/_/g, ' ')}
        </h3>

        {errorMsg && (
          <div className="mb-2 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {errorMsg}
          </div>
        )}

        {formColumns.length === 0 ? (
          <div className="text-sm text-gray-600">
            No editable columns configured for this table.
          </div>
        ) : (
          formColumns.map((col) => (
            <div key={col} className="mb-3">
              <label className="block text-sm font-medium text-gray-700">
                {col.replace(/_/g, ' ')}
              </label>
              {renderInput(col)}
            </div>
          ))
        )}

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="px-3 py-2 bg-gray-400 text-white rounded hover:bg-gray-300"
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            className="px-3 py-2 bg-green-700 text-white rounded hover:bg-green-600 disabled:opacity-60"
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
