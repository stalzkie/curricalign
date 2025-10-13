// src/components/dashboard/containers/MissingSkillsContainer.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import MissingSkillsList from '../MissingSkillsList';
import { useVersionWatcher } from '@/lib/useVersionWatcher';

// Define a constant for the desired minimum threshold
// Setting this to 5 forces the API to return any skill with a count >= 5, 
// overriding the dynamic 1% threshold for large datasets.
const FIXED_MIN_THRESHOLD = 5; 

// Note: The Fetcher type must now include the optional minThreshold
type Fetcher = (signal?: AbortSignal, minThreshold?: number) => Promise<string[]>;

export default function MissingSkillsContainer({
  fetcher,
  refetchIntervalMs,
  title = 'Missing Skills',
}: {
  // custom fetcher (defaults to dataService.getMissingSkills)
  fetcher?: Fetcher;
  // auto-refetch interval in ms (e.g., 60_000)
  refetchIntervalMs?: number;
  // panel title; purely cosmetic here
  title?: string;
}) {
  // Recompute when the dashboard version changes
  const versionIso = useVersionWatcher('missing-skills');

  // Lazy import to avoid hard crash if the function name changes during dev
  const defaultFetcher: Fetcher = async (signal?: AbortSignal, minThreshold?: number) => {
    const mod = await import('../../../lib/dataService');
    const fn =
      (mod as any).getMissingSkills ||
      (mod as any).fetchMissingSkills ||
      (mod as any).loadMissingSkills;
    if (!fn) {
      throw new Error(
        "No missing-skills fetcher found. Export getMissingSkills(): Promise<string[]> from lib/dataService."
      );
    }
    // Pass both the signal AND the threshold to dataService
    return fn(signal, minThreshold);
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<string[], Error>({
    // 1. INCLUDE the fixed threshold in the query key 
    // This ensures React Query treats requests with different thresholds as distinct.
    queryKey: ['missing-skills', versionIso ?? 'init', FIXED_MIN_THRESHOLD],
    
    // 2. PASS the fixed threshold to the fetcher function
    queryFn: ({ signal }) => (fetcher ?? defaultFetcher)(signal, FIXED_MIN_THRESHOLD),
    
    refetchInterval: refetchIntervalMs,
  });

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 flex-1 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-bold" style={{ color: '#EF4444' }}>
              {title}
            </h3>
            <div className="h-5 w-20 rounded bg-[var(--muted,#e5e7eb)] animate-pulse" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="p-3 rounded-lg border bg-red-100 border-red-200 animate-pulse"
                style={{ boxShadow: 'inset 4px 0 0 0 var(--brand-red, #EF4444)' }}
              >
                <div className="h-4 w-40 bg-[var(--muted,#e5e7eb)] rounded" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 flex-1 flex flex-col items-center justify-center gap-3 text-center">
          <h3 className="text-xl font-bold" style={{ color: '#EF4444' }}>
            {title}
          </h3>
          <p className="text-sm text-[var(--muted,#64748B)]">
            Failed to load missing skills{error?.message ? `: ${error.message}` : ''}.
          </p>
          <button
            onClick={() => refetch()}
            className="px-3 py-2 rounded-lg border border-[var(--foreground,#111827)]/20 hover:bg-black/5 transition"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  const skills = data ?? [];

  // Empty state
  if (!skills.length) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 flex-1 flex flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-xl font-bold" style={{ color: '#EF4444' }}>
            {title}
          </h3>
          <p className="text-sm text-[var(--muted,#64748B)]">No missing skills 🎉</p>
          <button
            onClick={() => refetch()}
            className="px-3 py-2 rounded-lg border border-[var(--foreground,#111827)]/20 hover:bg-black/5 transition"
          >
            Refresh
          </button>
        </div>
      </div>
    );
  }

  // Success
  return (
    <section aria-busy={isFetching ? 'true' : 'false'}>
      <MissingSkillsList data={skills} />
    </section>
  );
}