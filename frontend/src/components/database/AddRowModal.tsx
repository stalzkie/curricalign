'use client';

import { supabase } from '@/lib/supabaseClients';
import { useState } from 'react';

interface AddRowModalProps {
  tableName: string;
  columns: string[];
  onClose: () => void;
  onCreated: () => void; // caller will refetch
}

export default function AddRowModal({ tableName, columns, onClose, onCreated }: AddRowModalProps) {
  const [newRow, setNewRow] = useState<Record<string, any>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Build payload only with fields the user actually typed (avoid NULL spam)
  const buildPayload = () => {
    const payload: Record<string, any> = {};
    for (const c of columns) {
      const v = newRow[c];
      // Send only values that are non-empty strings or non-nullish
      if (v !== undefined && v !== null && String(v).trim() !== '') {
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

      // Optional: fail fast if nothing provided
      if (Object.keys(payload).length === 0) {
        setErrorMsg('Please fill at least one field.');
        setIsSaving(false);
        return;
      }

      // Insert and return the created row so we can confirm success
      const { data, error } = await supabase
        .from(tableName)
        .insert([payload])
        .select()
        .single();

      if (error) {
        // Common RLS message hint for quicker debugging
        const hint = /row-level security/i.test(error.message)
          ? ' (RLS may be blocking inserts for this table. Ensure an INSERT policy exists for your role.)'
          : '';
        setErrorMsg(`${error.message}${hint}`);
        setIsSaving(false);
        return;
      }

      // Success: reset + close + tell parent to refetch
      setNewRow({});
      onClose();
      onCreated();
    } catch (err: any) {
      setErrorMsg(err?.message ?? String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="max-h-[85vh] w-[92vw] max-w-2xl bg-white p-6 rounded-xl shadow-2xl overflow-auto">
        <h3 className="text-lg font-bold mb-4">Add New {tableName.replace(/_/g, ' ')}</h3>

        {errorMsg && (
          <div className="mb-2 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {errorMsg}
          </div>
        )}

        {columns.map((col) => (
          <div key={col} className="mb-2">
            <label className="block text-sm font-medium text-gray-700">
              {col.replace(/_/g, ' ')}
            </label>
            <input
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2"
              value={newRow[col] ?? ''}
              onChange={(e) =>
                setNewRow((prev) => ({ ...(prev ?? {}), [col]: e.target.value }))
              }
            />
          </div>
        ))}

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
            className="px-3 py-2 bg-[var(--brand-teal,#025864)] text-white rounded hover:opacity-90 disabled:opacity-60"
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
