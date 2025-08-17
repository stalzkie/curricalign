'use client';
import { RiLoader4Line, RiCheckboxBlankCircleLine, RiCheckLine, RiCloseCircleLine } from 'react-icons/ri';
import type { ProcessStep } from './types';

const stepStyles = (status: ProcessStep['status']) => {
  if (status === 'in-progress') return 'bg-[rgba(2,88,100,0.08)] border-[rgba(2,88,100,0.22)]';
  if (status === 'completed')   return 'bg-[rgba(0,212,126,0.10)] border-[rgba(0,212,126,0.25)]';
  if (status === 'error')       return 'bg-red-50 border-red-200';
  return 'bg-gray-50 border-gray-200';
};

const StepIcon = ({ status }: { status: ProcessStep['status'] }) => {
  if (status === 'completed')   return <RiCheckLine />;
  if (status === 'in-progress') return <RiLoader4Line className="animate-spin" />;
  if (status === 'error')       return <RiCloseCircleLine />;
  return <RiCheckboxBlankCircleLine />;
};

const stepColor = (status: ProcessStep['status']) =>
  status === 'in-progress' ? 'var(--brand-teal,#025864)'
  : status === 'completed' ? 'var(--brand-green,#00D47E)'
  : status === 'error'     ? '#B91C1C'
  : 'var(--muted,#64748B)';

export default function StepsList({ steps }: { steps: ProcessStep[] }) {
  return (
    <div className="space-y-3">
      {steps.map((s, i) => (
        <div key={s.id} className={`flex items-center gap-4 p-4 rounded-lg border transition-all ${stepStyles(s.status)}`}>
          <div className="text-2xl" style={{ color: stepColor(s.status) }}>
            <StepIcon status={s.status} />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-medium" style={{ color: stepColor(s.status) }}>{s.name}</h3>
            <p className="text_triaryColor text-xs">Step {i + 1} of {steps.length}</p>
          </div>
          {s.status === 'in-progress' && (
            <RiLoader4Line className="text-lg animate-spin" style={{ color: stepColor(s.status) }} />
          )}
        </div>
      ))}
    </div>
  );
}
