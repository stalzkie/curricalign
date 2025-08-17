// components/dashboard/containers/TopCoursesContainer.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import TopCoursesTable from '../TopCoursesTable';
import type { Course } from '../../../lib/dataService';

type Fetcher = () => Promise<Course[]>;

export default function TopCoursesContainer({
  fetcher,
  refetchIntervalMs,
  title = 'Top Matching Courses',
}: {
  /** Optional custom fetcher (defaults to dataService.getTopCourses) */
  fetcher?: Fetcher;
  /** Optional auto-refetch interval in ms (e.g., 60_000) */
  refetchIntervalMs?: number;
  /** Cosmetic title shown in skeleton/error/empty states */
  title?: string;
}) {
  // Lazy dynamic import to avoid hard crashes if names shift during dev
  const defaultFetcher: Fetcher = async () => {
    const mod = await import('../../../lib/dataService');
    const fn =
      (mod as any).getTopCourses ||
      (mod as any).fetchTopCourses ||
      (mod as any).getTopMatchingCourses ||
      (mod as any).fetchTopMatchingCourses;
    if (!fn) {
      throw new Error(
        "No courses fetcher found. Export getTopCourses(): Promise<Course[]> from lib/dataService."
      );
    }
    return fn();
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<Course[], Error>({
    queryKey: ['top-courses'],
    queryFn: fetcher ?? defaultFetcher,
    refetchInterval: refetchIntervalMs,
  });

  // --- Loading --------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
            <div className="h-5 w-20 rounded bg-[var(--muted,#e5e7eb)] animate-pulse" />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text_secondaryColor font-semibold py-3 px-2">Course Name</th>
                  <th className="text_secondaryColor font-semibold py-3 px-2">Course Code</th>
                  <th className="text_secondaryColor font-semibold py-3 px-2 text-center">Match %</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i} className="border-b border-gray-200">
                    <td className="py-3 px-2">
                      <div className="h-4 w-48 bg-[var(--muted,#e5e7eb)] rounded animate-pulse" />
                    </td>
                    <td className="py-3 px-2">
                      <div className="h-4 w-24 bg-[var(--muted,#e5e7eb)] rounded animate-pulse" />
                    </td>
                    <td className="py-3 px-2 text-center">
                      <div className="h-6 w-16 mx-auto bg-[var(--muted,#e5e7eb)] rounded-full animate-pulse" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  // --- Error ---------------------------------------------------------------
  if (isError) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-6 flex flex-col items-center justify-center gap-3 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">
            Failed to load courses{error?.message ? `: ${error.message}` : ''}.
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

  const courses = (data ?? []).filter(
    c => c?.courseName?.trim() && c?.courseCode?.trim()
  );

  // --- Empty ---------------------------------------------------------------
  if (!courses.length) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-6 flex flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">No courses to display.</p>
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

  // --- Success --------------------------------------------------------------
  return (
    <section aria-busy={isFetching ? 'true' : 'false'}>
      <TopCoursesTable data={courses} />
    </section>
  );
}
