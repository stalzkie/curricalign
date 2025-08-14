'use client';

import { useMemo, useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Label } from 'recharts';
import { Job } from '../../lib/dataService';

interface JobsPieChartProps {
  data: Job[];
}

const cssVar = (name: string, fallback: string) => {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

/** Robust center extraction for Recharts Label viewBox */
function getCenter(viewBox: any) {
  if (!viewBox) return { cx: 0, cy: 0 };
  if (typeof viewBox.cx === 'number' && typeof viewBox.cy === 'number') {
    return { cx: viewBox.cx, cy: viewBox.cy };
  }
  if (
    typeof viewBox.x === 'number' &&
    typeof viewBox.y === 'number' &&
    typeof viewBox.width === 'number' &&
    typeof viewBox.height === 'number'
  ) {
    return { cx: viewBox.x + viewBox.width / 2, cy: viewBox.y + viewBox.height / 2 };
  }
  return { cx: 0, cy: 0 };
}

export default function JobsPieChart({ data }: JobsPieChartProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const COLORS = useMemo(() => {
    const teal = cssVar('--brand-teal', '#025864');
    const green = cssVar('--brand-green', '#00D47E');
    return [teal, green, '#047481', '#10B981', '#059669', '#14B8A6', '#0EA5A5', '#22C55E', '#34D399', '#94A3B8'];
  }, []);

  const totalDemand = useMemo(() => data.reduce((s, j) => s + j.demand, 0), [data]);

  const sorted = useMemo(
    () =>
      [...data]
        .sort((a, b) => b.demand - a.demand)
        .map((j, i) => ({
          ...j,
          index: i,
          percent: totalDemand ? (j.demand / totalDemand) * 100 : 0,
          color: COLORS[i % COLORS.length],
        })),
    [data, totalDemand, COLORS]
  );

  const selected = selectedIndex != null ? sorted[selectedIndex] : null;

  const handleSelect = (idx: number) => setSelectedIndex(prev => (prev === idx ? null : idx));

  const CustomLegend = () => (
    <ul className="space-y-2">
      {sorted.map(item => {
        const isActive = selectedIndex === item.index || selectedIndex === null;
        return (
          <li
            key={item.index}
            className="flex items-center gap-2 cursor-pointer select-none"
            onClick={() => handleSelect(item.index)}
          >
            <span
              className="inline-block w-3 h-3 rounded"
              style={{ background: item.color, opacity: isActive ? 1 : 0.4 }}
            />
            <span
              className="text-sm"
              style={{
                color: selectedIndex === item.index ? cssVar('--brand-teal', '#025864') : cssVar('--muted', '#64748B'),
                opacity: isActive ? 1 : 0.6,
              }}
            >
              {item.title}
            </span>
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="btn_border_silver h-96">
      <div className="card_background rounded p-6 h-full">
        <h3 className="text-xl font-bold text_defaultColor mb-4">In-Demand Jobs</h3>

        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={sorted}
              cx="50%"
              cy="50%"
              innerRadius="55%"
              outerRadius="80%"
              dataKey="demand"
              nameKey="title"
              isAnimationActive={false}
              onClick={(_, idx) => handleSelect(idx)}
              stroke="none"                 // no ring on the whole pie
            >
              {sorted.map((entry, idx) => (
                <Cell
                  key={`cell-${idx}`}
                  fill={entry.color}
                  fillOpacity={selectedIndex === null ? 1 : selectedIndex === idx ? 1 : 0.35}
                  stroke="none"              // no ring on individual slice
                  strokeWidth={0}
                  style={{ cursor: 'pointer', outline: 'none' }}
                  tabIndex={-1}
                />
              ))}

              {selected && (
                <Label
                  position="center"
                  content={({ viewBox }) => {
                    const { cx, cy } = getCenter(viewBox);
                    return (
                      <g>
                        <text
                          x={cx}
                          y={cy}
                          textAnchor="middle"
                          dominantBaseline="central"
                          style={{ fill: cssVar('--foreground', '#0F172A') }}
                          fontSize={22}
                          fontWeight={800}
                        >
                          {selected.percent.toFixed(1)}%
                        </text>
                        <text
                          x={cx}
                          y={cy + 18}
                          textAnchor="middle"
                          dominantBaseline="hanging"
                          style={{ fill: cssVar('--muted', '#64748B') }}
                          fontSize={9}
                        >
                          {selected.title}
                        </text>
                      </g>
                    );
                  }}
                />
              )}
            </Pie>

            <Legend verticalAlign="middle" align="right" layout="vertical" content={<CustomLegend />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Remove any browser focus outlines on Recharts paths */}
      <style jsx global>{`
        .recharts-sector:focus,
        .recharts-pie-sector:focus,
        .recharts-surface path:focus {
          outline: none !important;
        }
      `}</style>
    </div>
  );
}
