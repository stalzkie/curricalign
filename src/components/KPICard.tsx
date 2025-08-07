'use client';

interface KPICardProps {
  title: string;
  value: string | number;
  icon: string;
}

export default function KPICard({ title, value, icon }: KPICardProps) {
  return (
    <div className="btn_border_silver">
      <div className="card_background_dark rounded p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-gray-300 text-sm font-medium">{title}</p>
            <p className="text-3xl font-bold mt-2">{value}</p>
          </div>
          <div className="text-4xl opacity-80">
            {icon}
          </div>
        </div>
      </div>
    </div>
  );
}
