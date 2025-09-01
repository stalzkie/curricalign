// src/components/dashboard/containers/KPIContainer.tsx
'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import KPICard from '../KPICard';
import {
  RiBarChartFill,
  RiBook2Fill,
  RiFileListFill,
  RiLightbulbFill,
} from 'react-icons/ri';
import type { KPIData } from '../../../lib/dataService';
import { useVersionWatcher } from '@/lib/useVersionWatcher';

type Fetcher = (signal?: AbortSignal) => Promise<KPIData>;

function formatNumber(n: number | undefined) {
  return new Intl.NumberFormat().format(n ?? 0);
}
function formatPercent(n: number | undefined) {
  if (n == null || Number.isNaN(n)) return '0%';
  const val = n <= 1 ? n * 100 : n; // handle 0–1 vs 0–100
  return `${Math.round(val)}%`;
}

export default function KPIContainer({
  fetcher,
  refetchIntervalMs,
  title = 'Key Metrics',
}: {
  fetcher?: Fetcher;            // defaults to dataService.fetchKPIData
  refetchIntervalMs?: number;   // optional auto-refetch interval
  title?: string;               // cosmetic title
}) {
  // Recompute when the dashboard version changes
  const versionIso = useVersionWatcher('kpi');

  // Lazy import so name changes in dataService don’t crash this file
  const defaultFetcher: Fetcher = async (signal?: AbortSignal) => {
    const mod = await import('../../../lib/dataService');
    const fn = (mod as any).fetchKPIData;
    if (!fn) {
      throw new Error(
        'dataService.fetchKPIData() not found. Export a function that returns Promise<KPIData>.'
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
  } = useQuery<KPIData, Error>({
    // include versionIso so changes to /version invalidate and refetch
    queryKey: ['kpis', versionIso ?? 'init'],
    queryFn: ({ signal }) => (fetcher ?? defaultFetcher)(signal),
    refetchInterval: refetchIntervalMs,
  });

  const safe = useMemo<KPIData>(
    () => ({
      averageAlignmentScore: Number(data?.averageAlignmentScore) || 0,
      totalSubjectsAnalyzed: Number(data?.totalSubjectsAnalyzed) || 0,
      totalJobPostsAnalyzed: Number(data?.totalJobPostsAnalyzed) || 0,
      skillsExtracted: Number((data as any)?.skillsExtracted) || 0,
    }),
    [data]
  );

  const isEmpty =
    safe.averageAlignmentScore === 0 &&
    safe.totalSubjectsAnalyzed === 0 &&
    safe.totalJobPostsAnalyzed === 0 &&
    safe.skillsExtracted === 0;

  // Loading
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="btn_border_silver">
            <div className="card_background rounded p-4 h-[108px] animate-pulse">
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <div className="h-4 w-36 rounded bg-[var(--muted,#e5e7eb)]" />
                  <div className="h-7 w-24 rounded bg-[var(--muted,#e5e7eb)]" />
                </div>
                <div className="h-8 w-8 rounded bg-[var(--muted,#e5e7eb)]" />
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Error
  if (isError) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-4 flex items-center justify-between">
          <div>
            <p className="text_defaultColor font-semibold">{title} failed to load</p>
            <p className="text-sm text-[var(--muted,#64748B)]">
              {error.message || 'An unknown error occurred.'}
            </p>
          </div>
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
  if (isEmpty) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-4 flex items-center justify-between">
          <div>
            <p className="text_defaultColor font-semibold">{title}</p>
            <p className="text-sm text-[var(--muted,#64748B)]">No KPI data yet.</p>
          </div>
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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KPICard
          title="Average Alignment Score"
          value={formatPercent(safe.averageAlignmentScore)}
          icon={<RiBarChartFill />}
        />
        <KPICard
          title="Total Subjects Analyzed"
          value={formatNumber(safe.totalSubjectsAnalyzed)}
          icon={<RiBook2Fill />}
        />
        <KPICard
          title="Total Job Posts Analyzed"
          value={formatNumber(safe.totalJobPostsAnalyzed)}
          icon={<RiFileListFill />}
        />
        <KPICard
          title="Skills Extracted"
          value={formatNumber(safe.skillsExtracted)}
          icon={<RiLightbulbFill />}
        />
      </div>
    </section>
  );
}
