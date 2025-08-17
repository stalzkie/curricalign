'use client';

import { useQuery } from '@tanstack/react-query';
import SkillsBarChart from '../SkillsBarChart';
import type { Skill } from '../../../lib/dataService';

type Fetcher = () => Promise<Skill[]>;

export default function MostInDemandSkillsContainer({
  fetcher,
  refetchIntervalMs,
  title = 'Most In-Demand Skills',
}: {
  // Optional custom fetcher (defaults to dataService.getMostInDemandSkills)
  fetcher?: Fetcher;
  // Optional auto-refetch interval in ms (e.g., 60_000) 
  refetchIntervalMs?: number;
  // Optional title (cosmetic) 
  title?: string;
}) {
  // Lazy dynamic import so minor renames in dataService don’t crash dev
  const defaultFetcher: Fetcher = async () => {
    const mod = await import('../../../lib/dataService');
    const fn =
      (mod as any).getMostInDemandSkills ||
      (mod as any).fetchMostInDemandSkills ||
      (mod as any).getTopSkills ||
      (mod as any).fetchTopSkills;
    if (!fn) {
      throw new Error(
        "No skills fetcher found. Export getMostInDemandSkills(): Promise<Skill[]> from lib/dataService."
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
  } = useQuery<Skill[], Error>({
    queryKey: ['most-in-demand-skills'],
    queryFn: fetcher ?? defaultFetcher,
    refetchInterval: refetchIntervalMs,
  });

  // Loading
  if (isLoading) {
    return (
      <div className="btn_border_silver h-[28rem] lg:h-[32rem]">
        <div className="card_background rounded p-6 h-full">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
            <div className="h-5 w-20 rounded bg-[var(--muted,#e5e7eb)] animate-pulse" />
          </div>
          <div className="h-[calc(100%-2rem)] grid grid-cols-12 gap-2 items-end">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="w-full">
                <div className="h-40 bg-[var(--muted,#e5e7eb)] rounded" />
                <div className="h-4 mt-2 bg-[var(--muted,#e5e7eb)] rounded" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Error
  if (isError) {
    return (
      <div className="btn_border_silver h-[28rem] lg:h-[32rem]">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-3 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">
            Failed to load skills{error?.message ? `: ${error.message}` : ''}.
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

  const skills = (data ?? []).filter(s => s?.name?.trim());

  // Empty
  if (!skills.length) {
    return (
      <div className="btn_border_silver h-[28rem] lg:h-[32rem]">
        <div className="card_background rounded p-6 h-full flex flex-col items-center justify-center gap-2 text-center">
          <h3 className="text-xl font-bold text_defaultColor">{title}</h3>
          <p className="text-sm text-[var(--muted,#64748B)]">No skills to display.</p>
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
      <SkillsBarChart data={skills} />
    </section>
  );
}
