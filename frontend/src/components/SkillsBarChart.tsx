'use client';

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Skill } from '@/lib/dataService';

interface SkillsBarChartProps {
  data: Skill[];
}

export default function SkillsBarChart({ data }: SkillsBarChartProps) {
  return (
    <div className="btn_border_silver h-96">
      <div className="card_background_dark rounded p-6 h-full">
        <h3 className="text-xl font-bold text-white mb-4">Most In-Demand Skills</h3>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis 
              dataKey="name" 
              stroke="#9CA3AF"
              angle={-45}
              textAnchor="end"
              height={80}
              fontSize={12}
            />
            <YAxis stroke="#9CA3AF" />
            <Tooltip 
              contentStyle={{ 
                backgroundColor: '#1F2937', 
                border: '1px solid #374151',
                borderRadius: '8px',
                color: '#F9FAFB'
              }}
            />
            <Bar 
              dataKey="demand" 
              fill="url(#skillGradient)"
              radius={[4, 4, 0, 0]}
            />
            <defs>
              <linearGradient id="skillGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#D088FF" />
                <stop offset="100%" stopColor="#9C0BFB" />
              </linearGradient>
            </defs>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
