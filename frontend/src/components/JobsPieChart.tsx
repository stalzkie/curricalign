'use client';

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Job } from '@/lib/dataService';

interface JobsPieChartProps {
  data: Job[];
}

const COLORS = [
  '#D088FF', '#9C0BFB', '#7C3AED', '#6366F1', '#3B82F6',
  '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#6B7280'
];

export default function JobsPieChart({ data }: JobsPieChartProps) {
  return (
    <div className="btn_border_silver h-96">
      <div className="card_background_dark rounded p-6 h-full">
        <h3 className="text-xl font-bold text-white mb-4">In-Demand Jobs</h3>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              outerRadius={100}
              fill="#8884d8"
              dataKey="demand"
              label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip 
              contentStyle={{ 
                backgroundColor: '#1F2937', 
                border: '1px solid #374151',
                borderRadius: '8px',
                color: '#F9FAFB'
              }}
            />
            <Legend 
              wrapperStyle={{ color: '#F9FAFB', fontSize: '12px' }}
              layout="vertical"
              align="right"
              verticalAlign="middle"
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
