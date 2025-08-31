'use client';

interface ViewRowModalProps {
  tableName: string;
  row: Record<string, any>;
  visibleColumns: string[];
  onClose: () => void;
}

export default function ViewRowModal({ tableName, row, visibleColumns, onClose }: ViewRowModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="max-h-[85vh] w-[92vw] max-w-2xl bg-white p-6 rounded-xl shadow-2xl overflow-auto">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-bold">Row details: {tableName}</h3>
          <button onClick={onClose} className="px-2 py-1 bg-gray-200 rounded">Close</button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {visibleColumns.map((col) => (
            <div key={col} className="border rounded p-2">
              <div className="text-xs text-gray-500">{col.replace(/_/g, ' ')}</div>
              <div className="text-sm break-words">{String(row[col] ?? '—')}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
