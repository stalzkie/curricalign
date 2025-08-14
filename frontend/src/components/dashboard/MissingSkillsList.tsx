'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

interface MissingSkillsListProps {
  data: string[];
}

export default function MissingSkillsList({ data }: MissingSkillsListProps) {
  const firstItemRef = useRef<HTMLDivElement | null>(null);
  const [itemHeight, setItemHeight] = useState<number | null>(null);

  // Tailwind space-y-2 = 0.5rem gap between rows
  const GAP_Y = 8;

  useEffect(() => {
    if (firstItemRef.current) {
      const h = firstItemRef.current.getBoundingClientRect().height;
      if (h > 0) setItemHeight(h);
    }
  }, [data]);

  const maxHeight = useMemo(() => {
    if (!itemHeight) return undefined;
    const visible = Math.min(9.5, data.length);
    return itemHeight * visible + GAP_Y * Math.max(0, visible - 1);
  }, [itemHeight, data.length]);

  return (
    <div className="btn_border_silver h-full max-h-full overflow-hidden flex flex-col">
      <div className="card_background rounded p-6 flex-1 flex flex-col">
        <h3 className="text-xl font-bold mb-4" style={{ color: '#EF4444' /* red-700 */ }}>Missing Skills</h3>

        {/* Scroll area sized to ~10 items */}
        <div
          className="min-h-0 flex-1 overflow-y-auto scrollbar-thin"
          style={maxHeight ? { maxHeight } : undefined}
        >
          <div className="space-y-2">
            {data.map((skill, index) => (
              <div
                key={index}
                ref={index === 0 ? firstItemRef : null}
                className="
                  flex items-center justify-between p-3 rounded-lg
                  border transition-colors
                  bg-red-100 border-red-200 hover:bg-white
                "
                style={{
                  // subtle left brand accent
                  boxShadow: 'inset 4px 0 0 0 var(--brand-red, #EF4444)',
                }}
              >
                <span className="text_defaultColor font-medium">{skill}</span>

                <div className="flex items-center space-x-2">
                  <span className="text-sm" style={{ color: '#B91C1C' /* red-700 */ }}>
                    Missing
                  </span>
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ background: '#EF4444' /* red-500 */ }}
                    aria-hidden="true"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
