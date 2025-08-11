'use client';

import { Course } from '../../lib/dataService';

interface TopCoursesTableProps {
  data: Course[];
}

export default function TopCoursesTable({ data }: TopCoursesTableProps) {
  const getMatchColor = (percentage: number) => {
    if (percentage >= 80) return 'text-green-400';
    if (percentage >= 60) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <div className="btn_border_silver">
      <div className="card_background_dark rounded p-6">
        <h3 className="text-xl font-bold text-white mb-4">Top Matching Courses</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-600">
                <th className="text-gray-300 font-semibold py-3 px-2">Course Name</th>
                <th className="text-gray-300 font-semibold py-3 px-2">Course Code</th>
                <th className="text-gray-300 font-semibold py-3 px-2 text-center">Match %</th>
              </tr>
            </thead>
            <tbody>
                {data
                  .sort((a, b) => b.matchPercentage - a.matchPercentage)
                  .slice(0, 10)
                  .map((course, index) => (
                <tr 
                  key={course.courseCode} 
                  className={`border-b border-gray-700 hover:bg-gray-800 transition-colors ${
                    index % 2 === 0 ? 'bg-gray-800/30' : ''
                  }`}
                >
                  <td className="text-white py-3 px-2 font-medium">{course.courseName}</td>
                  <td className="text-gray-300 py-3 px-2">{course.courseCode}</td>
                  <td className={`py-3 px-2 text-center font-bold ${getMatchColor(course.matchPercentage)}`}>
                    {course.matchPercentage}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
