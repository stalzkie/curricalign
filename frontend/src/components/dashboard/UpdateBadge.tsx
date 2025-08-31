// src/components/dashboard/UpdateBadge.tsx
'use client';

import { useEffect, useState } from 'react';
import { formatLastChanged } from '@/lib/dataCache';
import { useVersionWatcher } from '@/lib/useVersionWatcher';

export default function UpdateBadge({ tableName }: { tableName: string }) {
  // Ensure the component only renders its dynamic content after client mount
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const iso = useVersionWatcher(tableName);

  // On the server and on the client's first render, this returns null,
  // so the markup matches and avoids hydration errors.
  if (!mounted || !iso) return null;

  return (
    <div className="text-xs px-2 py-1 rounded-full border inline-flex items-center gap-2 opacity-80">
      <span>Recently updated on</span>
      <time suppressHydrationWarning>{formatLastChanged(iso)}</time>
    </div>
  );
}
