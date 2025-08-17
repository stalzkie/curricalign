'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchCourseWarnings, type Course } from '../../../lib/dataService';
import CourseWarningsList from '../CourseWarningsList';

export default function CourseWarningsContainer() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard', 'warnings'],
    queryFn: ({ signal }) => fetchCourseWarnings(signal),
    // Optional tweaks:
    // staleTime: 5 * 60 * 1000, // keep cached for 5 min
    // retry: 2,                  // retry a couple of times if it fails
  });

  // Fallbacks so the presentational component always gets an array
  const warnings: Course[] = data ?? [];

  if (isLoading && warnings.length === 0) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-6">
          <h3 className="text-xl font-bold text_defaultColor mb-4">Course Warnings</h3>
          <p className="text_secondaryColor text-sm">Loading…</p>
        </div>
      </div>
    );
  }

  if (isError && warnings.length === 0) {
    return (
      <div className="btn_border_silver">
        <div className="card_background rounded p-6">
          <h3 className="text-xl font-bold text_defaultColor mb-4">Course Warnings</h3>
          <p className="text_secondaryColor text-sm">Couldn’t load warnings. Showing nothing.</p>
        </div>
      </div>
    );
  }

  return <CourseWarningsList data={warnings} />;
}
