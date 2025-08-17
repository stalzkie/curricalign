// components/dashboard/containers/KPIContainer.tsx
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

type Fetcher = () => Promise<KPIData>;

function formatNumber(n: number | undefined) {
  return new Intl.NumberFormat().format(n ?? 0);
}
function formatPercent(n: number | undefined) {
  if (n == null || Number.isNaN(n)) return '0%';
  // handle values like 0.82 vs 82 (backend differences)
  const val = n <= 1 ? n * 100 : n;
  return `${Math.round(val)}%`;
}

export default function KPIContainer({
  fetcher,
  refetchIntervalMs,
}: {
  /** Optional custom fetcher (defaults to dataService.fetchKPIData) */
  fetcher?: Fetcher;
  /** Optional auto-refetch interval in ms (e.g. 60_000) */
  refetchIntervalMs?: number;
}) {
  const defaultFetcher: Fetcher = async () => {
    const mod = await import('../../../lib/dataService');
    if (!('fetchKPIData' in mod)) {
      throw new Error(
        'dataService.fetchKPIData() not found. Export a function that returns Promise<KPIData>.'
      );
    }
    return mod.fetchKPIData();
  };

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery<KPIData, Error>({
    queryKey: ['kpis'],
    queryFn: fetcher ?? defaultFetcher,
    refetchInterval: refetchIntervalMs,
  });

  const safe = useMemo<KPIData>(
    () => ({
      averageAlignmentScore: data?.averageAlignmentScore ?? 0,
      totalSubjectsAnalyzed: data?.totalSubjectsAnalyzed ?? 0,
      totalJobPostsAnalyzed: data?.totalJobPostsAnalyzed ?? 0,
      // some older payloads might omit this field
      skillsExtracted: (data as any)?.skillsExtracted ?? 0,
    }),
    [data]
  );

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

  if (isError) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-4 flex items-center justify-between">
          <div>
            <p className="text_defaultColor font-semibold">KPIs failed to load</p>
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
          value={formatNumber((safe as any).skillsExtracted)}
          icon={<RiLightbulbFill />}
        />
      </div>
    </section>
  );
}
