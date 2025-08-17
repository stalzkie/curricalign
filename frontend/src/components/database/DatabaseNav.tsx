'use client';

interface Props {
  active: string;
  onChange: (table: string) => void;
}

const TABLES = [
  "courses",
  "jobs",
  "job_skills",
  "course_skills",
  "course_alignment_scores",
  "reports"
];

export default function DatabaseNav({ active, onChange }: Props) {
  return (
    <nav className="btn_border_silver card_background rounded mb-6">
      <div className="flex flex-wrap gap-2 sm:gap-4 p-4">
        {TABLES.map((t) => {
          const isActive = active === t;
          return (
            <button
              key={t}
              onClick={() => onChange(t)}
              className={`relative px-4 py-2 text-sm sm:text-base font-medium rounded-md transition-colors
                ${
                  isActive
                    ? "text_defaultColor"
                    : "text_secondaryColor hover:text_defaultColor"
                }`}
            >
              {t.replace(/_/g, " ")}

              {/* Brand underline for active tab */}
              {isActive && (
                <span
                  className="absolute left-0 right-0 -bottom-[2px] h-[3px] rounded"
                  style={{
                    background:
                      'linear-gradient(90deg, var(--brand-teal, #025864), var(--brand-green, #00D47E))',
                  }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
