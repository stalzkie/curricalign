'use client';

import { JSX } from "react";

interface KPICardProps {
  title: string;
  value: string | number;
  icon: JSX.Element; // react-icons element
}

export default function KPICard({ title, value, icon }: KPICardProps) {
  return (
    <div className="btn_border_silver">
      <div className="card_background rounded p-6 text_defaultColor">
        <div className="flex items-center justify-between">
          {/* Text block */}
          <div>
            <p className="text_secondaryColor text-sm font-medium">{title}</p>
            <p className="text-3xl font-bold mt-2">{value}</p>

            {/* subtle brand underline */}
            <span
              className="mt-3 block h-[3px] rounded"
              style={{
                background:
                  'linear-gradient(90deg, var(--brand-teal, #025864), var(--brand-green, #00D47E))',
                width: 64,
              }}
            />
          </div>

          {/* Icon without background */}
          <span
            className="text-4xl leading-none"
            style={{ color: 'var(--brand-teal, #025864)' }}
            aria-hidden="true"
          >
            {icon}
          </span>
        </div>
      </div>
    </div>
  );
}
