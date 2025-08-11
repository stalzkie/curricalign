'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

interface MissingSkillsListProps {
  data: string[];
}

export default function MissingSkillsList({ data }: MissingSkillsListProps) {
  const firstItemRef = useRef<HTMLDivElement | null>(null);
  const [itemHeight, setItemHeight] = useState<number | null>(null);

  // Tailwind `space-y-2` = 0.5rem = 8px vertical gap between items
  const GAP_Y = 8;

  useEffect(() => {
    if (firstItemRef.current) {
      // Measure including padding/border; margin is handled by GAP_Y
      const h = firstItemRef.current.getBoundingClientRect().height;
      if (h > 0) setItemHeight(h);
    }
  }, [data]);

  const maxHeight = useMemo(() => {
    if (!itemHeight) return undefined; // falls back to natural height until measured
    const visible = Math.min(9.5, data.length);
    // 10 items + 9 gaps (space-y-2 adds gaps between siblings only)
    return itemHeight * visible + GAP_Y * Math.max(0, visible - 1);
  }, [itemHeight, data.length]);

  return (
    <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
      <div className="card_background_dark rounded p-6 flex-1 flex flex-col">
        <h3 className="text-xl font-bold text-white mb-4">Missing Skills</h3>

        {/* scroll area set to show exactly 10 items */}
        <div
          className="min-h-0 flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-800"
          style={maxHeight ? { maxHeight } : undefined}
        >
          <div className="space-y-2">
            {data.map((skill, index) => (
              <div
                key={index}
                ref={index === 0 ? firstItemRef : null}
                className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg border border-gray-700 hover:bg-gray-700/50 transition-colors"
              >
                <span className="text-white font-medium">{skill}</span>
                <div className="flex items-center space-x-2">
                  <span className="text-red-400 text-sm">Missing</span>
                  <div className="w-2 h-2 bg-red-500 rounded-full" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
