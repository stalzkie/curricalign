'use client';

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Job } from '../lib/dataService';

interface JobsPieChartProps {
  data: Job[];
}

const COLORS = [
  '#D088FF', '#9C0BFB', '#7C3AED', '#6366F1', '#3B82F6',
  '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#6B7280'
];

export default function JobsPieChart({ data }: JobsPieChartProps) {
  // ✅ Calculate total demand
  const totalDemand = data.reduce((sum, job) => sum + job.demand, 0);

  // ✅ Sort by demand and append percentage to title
  const sortedData = [...data]
    .sort((a, b) => b.demand - a.demand)
    .map(job => ({
      ...job,
      title: `${job.title} (${((job.demand / totalDemand) * 100).toFixed(1)}%)`
    }));

  return (
    <div className="btn_border_silver h-96">
      <div className="card_background_dark rounded p-6 h-full">
        <h3 className="text-xl font-bold text-white mb-4">In-Demand Jobs</h3>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={sortedData}
              cx="50%"
              cy="50%"
              outerRadius={100}
              fill="#8884d8"
              dataKey="demand"
              nameKey="title" // Title now includes percentage
            >
              {sortedData.map((entry, index) => (
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
              formatter={(value: number, name: string) => [`${value}`, name]}
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
