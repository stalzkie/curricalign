'use client';

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Skill } from '../../lib/dataService';

interface SkillsBarChartProps {
  data: Skill[];
}

export default function SkillsBarChart({ data }: SkillsBarChartProps) {
  // Take top 20 valid skills by demand
  const filteredData = data
    .filter((s) => s.name && s.name.trim() !== '')
    .sort((a, b) => b.demand - a.demand)
    .slice(0, 20);

  // Tokens from global.css
  const colorMuted   = 'var(--muted, #64748B)';
  const colorMuted2  = 'var(--muted-2, #94A3B8)';
  const colorSurface = 'var(--surface, #F7F9FB)';
  const colorFg      = 'var(--foreground, #0F172A)';
  const brandTealTint= 'var(--brand-teal-20, rgba(2,88,100,0.20))';

  return (
    <div className="btn_border_silver h-[28rem] lg:h-[32rem]">
      <div className="card_background rounded p-6 h-full">
        <h3 className="text-xl font-bold text_defaultColor mb-4">Most In-Demand Skills</h3>

        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={filteredData} margin={{ top: 20, right: 30, left: 12, bottom: 100 }}>
            {/* light, subtle grid */}
            <CartesianGrid strokeDasharray="3 3" stroke={colorMuted2} />

            {/* axes in muted tokens */}
            <XAxis
              dataKey="name"
              stroke={colorMuted2}
              angle={-45}
              textAnchor="end"
              height={100}
              fontSize={12}
            />
            <YAxis stroke={colorMuted2} />

            {/* light tooltip styled via tokens */}
            <Tooltip
              cursor={{ fill: 'rgba(0,0,0,0.03)' }}
              contentStyle={{
                backgroundColor: colorSurface as string,
                border: `1px solid ${brandTealTint}`,
                borderRadius: 8,
                color: colorFg as string,
                fontFamily: 'Figtree, ui-sans-serif, system-ui',
              }}
              labelStyle={{ color: colorMuted as string, fontWeight: 500 }}
              itemStyle={{ color: colorFg as string }}
            />

            {/* all bars: same solid color */}
            <Bar dataKey="demand" fill="#059669" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
