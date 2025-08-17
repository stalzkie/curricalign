// components/dashboard/InDemandJobsContainer.tsx
'use client';

import { useQuery } from '@tanstack/react-query';
import JobsPieChart from '../JobsPieChart';
import { Job } from '../../../lib/dataService';

type Fetcher = () => Promise<Job[]>;

export default function InDemandJobsContainer({
  fetcher,
  title = 'In-Demand Jobs',
  refetchIntervalMs,
}: {
  /** Optional custom fetcher (defaults to dataService.getInDemandJobs) */
  fetcher?: Fetcher;
  /** Optional panel title */
  title?: string;
  /** Optional auto-refetch interval in ms (e.g., 60_000) */
  refetchIntervalMs?: number;
}) {
  // lazy import so this file doesn’t hard-crash if the function name differs during dev
  const defaultFetcher: Fetcher = async () => {
    const mod = await import('../../../lib/dataService');
    if (!('getInDemandJobs' in mod)) {
      throw new Error(
        'dataService.getInDemandJobs() not found. Export a function that returns Promise<Job[]>'
      );
    }
    return mod.getInDemandJobs();
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<Job[], Error>({
    queryKey: ['in-demand-jobs'],
    queryFn: fetcher ?? defaultFetcher,
    refetchInterval: refetchIntervalMs,
  });

  // ---- UI states -----------------------------------------------------------
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
