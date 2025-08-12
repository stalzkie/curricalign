'use client';

import { useMemo, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Legend,
  Label
} from 'recharts';
import { Job } from '../../lib/dataService';

interface JobsPieChartProps {
  data: Job[];
}

const COLORS = [
  '#D088FF', '#9C0BFB', '#7C3AED', '#6366F1', '#3B82F6',
  '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#6B7280'
];

export default function JobsPieChart({ data }: JobsPieChartProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const totalDemand = useMemo(
    () => data.reduce((s, j) => s + j.demand, 0),
    [data]
  );

  const sorted = useMemo(() => {
    return [...data]
      .sort((a, b) => b.demand - a.demand)
      .map((j, i) => ({
        ...j,
        index: i,
        percent: totalDemand ? (j.demand / totalDemand) * 100 : 0,
        color: COLORS[i % COLORS.length],
      }));
  }, [data, totalDemand]);

  const selected = selectedIndex != null ? sorted[selectedIndex] : null;

  const handleSelect = (idx: number) => {
    setSelectedIndex(prev => (prev === idx ? null : idx));
  };

  const CustomLegend = () => (
    <ul className="space-y-2">
      {sorted.map(item => {
        const isActive = selectedIndex === item.index;
        return (
          <li
            key={item.index}
            className="flex items-center gap-2 cursor-pointer select-none"
            onClick={() => handleSelect(item.index)}
          >
            <span
              className="inline-block w-3 h-3 rounded"
              style={{
                background: item.color,
                opacity: isActive || selectedIndex === null ? 1 : 0.4,
              }}
            />
            <span
              className={`text-sm ${isActive ? 'text-white' : 'text-gray-300'}`}
              style={{
                opacity: isActive || selectedIndex === null ? 1 : 0.6,
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
            >
              {sorted.map((entry, idx) => (
                <Cell
                  key={`cell-${idx}`}
                  fill={entry.color}
                  fillOpacity={
                    selectedIndex === null
                      ? 1
                      : selectedIndex === idx
                      ? 1
                      : 0.35
                  }
                  stroke={selectedIndex === idx ? '#ffffff' : 'none'}
                  strokeWidth={selectedIndex === idx ? 2 : 0}
                  style={{ cursor: 'pointer' }}
                />
              ))}

              {/* Center label inside the pie */}
              {selected && (
                <Label
                  position="center"
                  content={(props: any) => {
                    const cx = props.cx || props.viewBox?.cx || 0;
                    const cy = props.cy || props.viewBox?.cy || 0;
                    
                    return (
                      <g>
                        <text
                          x={cx}
                          y={cy - 8}
                          textAnchor="middle"
                          dominantBaseline="middle"
                          fill="#E5E7EB"
                          fontSize={12}
                        >
                          {selected.title}
                        </text>
                        <text
                          x={cx}
                          y={cy + 12}
                          textAnchor="middle"
                          dominantBaseline="middle"
                          fill="#FFFFFF"
                          fontSize={16}
                          fontWeight={700}
                        >
                          {selected.demand.toLocaleString()} • {selected.percent.toFixed(1)}%
                        </text>
                      </g>
                    );
                  }}
                />
              )}
            </Pie>

            <Legend
              verticalAlign="middle"
              align="right"
              layout="vertical"
              content={<CustomLegend />}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}