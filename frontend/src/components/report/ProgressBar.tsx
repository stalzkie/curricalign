'use client';

export default function ProgressBar({ completed, total }: { completed: number; total: number }) {
  const pct = (completed / Math.max(1, total)) * 100;
  return (
    <div className="mt-6">
      <div className="flex justify-between text-sm text_secondaryColor mb-2">
        <span>Progress</span>
        <span>{completed} / {total} completed</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3">
        <div
          className="h-3 rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(90deg, var(--brand-teal,#025864), var(--brand-green,#00D47E))',
          }}
        />
      </div>
    </div>
  );
}
