// src/components/UpdatedBadge.tsx
'use client';
import { formatLastChanged } from "@/lib/dataCache";
import { useVersionWatcher } from "@/lib/useVersionWatcher";

export default function UpdatedBadge() {
  const iso = useVersionWatcher();
  if (!iso) return null;

  return (
    <div className="text-xs px-2 py-1 rounded-full border inline-flex items-center gap-2 opacity-80">
      <span>Recently updated on</span>
      <time suppressHydrationWarning>{formatLastChanged(iso)}</time>
    </div>
  );
}
