// src/components/dashboard/containers/InDemandJobsContainer.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import JobsPieChart from '../JobsPieChart';
import type { Job } from '../../../lib/dataService';
import { useVersionWatcher } from '@/lib/useVersionWatcher';

type Fetcher = (signal?: AbortSignal) => Promise<Job[]>;

export default function InDemandJobsContainer({
  fetcher,
  title = 'In-Demand Jobs',
  refetchIntervalMs,
}: {
  fetcher?: Fetcher;        // custom fetcher (defaults to dataService.getInDemandJobs)
  title?: string;           // panel title
  refetchIntervalMs?: number; // auto-refetch interval in ms (e.g., 60_000)
}) {
  // Refetch whenever the dashboard version changes
  const versionIso = useVersionWatcher('jobs');

  // Lazy import and pass AbortSignal through (React Query supplies it)
  const defaultFetcher: Fetcher = async (signal?: AbortSignal) => {
    const mod = await import('../../../lib/dataService');
    const fn =
      (mod as any).getInDemandJobs ||
      (mod as any).fetchInDemandJobs;
    if (!fn) {
      throw new Error(
        'dataService.getInDemandJobs() not found. Export a function that returns Promise<Job[]>'
      );
    }
    return fn(signal);
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<Job[], Error>({
    // include versionIso so a new /version invalidates this cache key
    queryKey: ['in-demand-jobs', versionIso ?? 'init'],
    queryFn: ({ signal }) => (fetcher ?? defaultFetcher)(signal),
    refetchInterval: refetchIntervalMs,
  });

  // UI states
  if (isLoading) {
    return (
      <div className="btn_border_silver h-96">
        <div className="card_background rounded p-6 h-full animate-pulse">
          <div className="flex items-center justify-between mb-4">
            <div className="h-6 w-40 rounded bg-[var(--muted,#e5e7eb)]" />
            <div className="h-5 w-20 rounded bg-[var(--muted,#e5e7eb)]" />
          </div>
          <div className="h-[calc(100%-2rem)] rounded bg-[var(--muted,#e5e7eb)]" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="btn_border_silver h-96">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-3 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">
            Failed to load jobs{error?.message ? `: ${error.message}` : ''}.
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

  const jobs = data ?? [];
  if (!jobs.length) {
    return (
      <div className="btn_border_silver h-96">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">No data available yet.</p>
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

  return (
    <section aria-busy={isFetching ? 'true' : 'false'}>
      <JobsPieChart data={jobs} />
    </section>
  );
}
