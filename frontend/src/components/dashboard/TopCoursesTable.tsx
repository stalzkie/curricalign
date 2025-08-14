'use client';

import { Course } from '../../lib/dataService';

interface TopCoursesTableProps {
  data: Course[];
}

export default function TopCoursesTable({ data }: TopCoursesTableProps) {
  const getMatchStyles = (percentage: number) => {
    // High (>=80): brand green
    if (percentage >= 80) {
      return {
        bg: 'var(--brand-green-10, rgba(0,212,126,0.10))',
        color: 'var(--brand-green, #00D47E)',
        border: '1px solid rgba(0,212,126,0.25)',
        labelClass: 'font-bold',
      };
    }
    // Medium (>=60): amber
    if (percentage >= 60) {
      return {
        bg: 'rgba(245, 158, 11, 0.10)', // amber-500 @10%
        color: '#B45309',               // amber-700
        border: '1px solid rgba(245, 158, 11, 0.25)',
        labelClass: 'font-semibold',
      };
    }
    // Low (<60): red
    return {
      bg: 'rgba(239, 68, 68, 0.10)',   // red-500 @10%
      color: '#B91C1C',                // red-700
      border: '1px solid rgba(239, 68, 68, 0.25)',
      labelClass: 'font-semibold',
    };
  };

  const rows = [...data]
    .sort((a, b) => b.matchPercentage - a.matchPercentage)
    .slice(0, 10);

  return (
    <div className="btn_border_silver">
      <div className="card_background rounded p-6">
        <h3 className="text-xl font-bold text_defaultColor mb-4">Top Matching Courses</h3>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text_secondaryColor font-semibold py-3 px-2">Course Name</th>
                <th className="text_secondaryColor font-semibold py-3 px-2">Course Code</th>
                <th className="text_secondaryColor font-semibold py-3 px-2 text-center">Match %</th>
              </tr>
            </thead>

            <tbody>
              {rows.map((course, index) => {
                const styles = getMatchStyles(course.matchPercentage);
                return (
                  <tr
                    key={course.courseCode}
                    className={`border-b border-gray-200 transition-colors ${
                      index % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                    } hover:bg-gray-100`}
                  >
                    <td className="text_defaultColor py-3 px-2 font-medium">
                      {course.courseName}
                    </td>
                    <td className="text_secondaryColor py-3 px-2">
                      {course.courseCode}
                    </td>
                    <td className="py-3 px-2 text-center">
                      <span
                        className={`inline-flex items-center justify-center px-2.5 py-1 rounded-full text-xs ${styles.labelClass}`}
                        style={{
                          background: styles.bg,
                          color: styles.color,
                          border: styles.border,
                          minWidth: 56,
                        }}
                      >
                        {course.matchPercentage}%
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

      </div>
    </div>
  );
}
