// src/components/dashboard/containers/CourseWarningsContainer.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import CourseWarningsList from '../CourseWarningsList';
import type { Course } from '../../../lib/dataService';
import { useVersionWatcher } from '@/lib/useVersionWatcher';

type Fetcher = (signal?: AbortSignal) => Promise<Course[]>;

export default function CourseWarningsContainer({
  fetcher,
  refetchIntervalMs,
  title = 'Course Warnings',
}: {
  // custom fetcher (defaults to dataService.fetchCourseWarnings / getCourseWarnings)
  fetcher?: Fetcher;
  // auto-refetch interval in ms (e.g., 60_000)
  refetchIntervalMs?: number;
  // Cosmetic title
  title?: string;
}) {
  // Watch the dashboard version. When this ISO changes, we'll refetch.
  const versionIso = useVersionWatcher('warnings');

  // Lazy dynamic import (and pass AbortSignal through)
  const defaultFetcher: Fetcher = async (signal?: AbortSignal) => {
    const mod = await import('../../../lib/dataService');
    const fn =
      (mod as any).fetchCourseWarnings ||
      (mod as any).getCourseWarnings;
    if (!fn) throw new Error('No course warnings fetcher found in dataService.');
    // dataService.fetchCourseWarnings accepts (signal?: AbortSignal)
    return fn(signal);
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<Course[], Error>({
    // Include versionIso so cache invalidates & refetches on version change
    queryKey: ['course-warnings', versionIso ?? 'init'],
    queryFn: ({ signal }) => (fetcher ?? defaultFetcher)(signal),
    refetchInterval: refetchIntervalMs,
  });

  const warnings = (data ?? []).filter((c) => c?.courseCode && c?.courseName);

  // Loading
  if (isLoading) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 flex-1 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
            <div className="h-5 w-20 rounded bg-[var(--muted,#e5e7eb)] animate-pulse" />
          </div>
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="p-3 rounded-lg border bg-[var(--surface,#F7F9FB)] animate-pulse"
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Error
  if (isError) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-3 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">
            Failed to load warnings{error?.message ? `: ${error.message}` : ''}.
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

  // Empty
  if (!warnings.length) {
    return (
      <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">No course warnings at the moment.</p>
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
      <CourseWarningsList data={warnings} />
    </section>
  );
}
