'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Course } from '../../lib/dataService';

interface CourseWarningsListProps {
  data: Course[];
}

export default function CourseWarningsList({ data }: CourseWarningsListProps) {
  const TARGET = 2.77;
  const firstItemRef = useRef<HTMLDivElement | null>(null);
  const [itemHeight, setItemHeight] = useState<number | null>(null);
  const GAP_Y = 12; // space-y-3

  const shouldScroll = data.length > TARGET;

  useEffect(() => {
    if (firstItemRef.current) {
      const h = firstItemRef.current.getBoundingClientRect().height;
      if (h > 0) setItemHeight(h);
    } else {
      setItemHeight(null);
    }
  }, [data]); // re-measure when list size changes

  const maxHeight = useMemo(() => {
    if (!itemHeight || !shouldScroll) return undefined;
    // exactly TARGET items tall when scrolling is needed
    return itemHeight * TARGET + GAP_Y * (TARGET - 1);
  }, [itemHeight, shouldScroll]);

  const getWarningLevel = (p: number) => {
    if (p < 30) return { color: 'text-red-400', bg: 'bg-red-900/30', level: 'Critical' };
    if (p < 50) return { color: 'text-yellow-400', bg: 'bg-yellow-900/30', level: 'Warning' };
    return { color: 'text-orange-400', bg: 'bg-orange-900/30', level: 'Low Match' };
  };

  return (
    <div className="btn_border_silver overflow-hidden"> {/* no h-full here */}
      <div className="card_background rounded p-6 flex flex-col"> {/* no flex-1 */}
        <h3 className="text-xl font-bold text_defaultColor mb-4">Course Warnings</h3>

        <div
          className={`${shouldScroll ? 'overflow-y-auto' : 'overflow-visible'} min-h-0`}
          style={maxHeight ? { maxHeight } : undefined}
        >
          <div className="space-y-3">
            {data.map((course, index) => {
              const warning = getWarningLevel(course.matchPercentage);
              return (
                <div
                  key={index}
                  ref={index === 0 ? firstItemRef : null}
                  className={`p-4 rounded-lg border border-gray-700 hover:bg-gray-700/30 transition-colors ${warning.bg}`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h4 className="text-white font-semibold text-sm">{course.courseName}</h4>
                      <p className="text-gray-300 text-xs mt-1">{course.courseCode}</p>
                    </div>
                    <div className="text-right ml-4">
                      <div className={`text-lg font-bold ${warning.color}`}>{course.matchPercentage}%</div>
                      <div className={`text-xs ${warning.color}`}>{warning.level}</div>
                    </div>
                  </div>
                  <div className="mt-3">
                    <div className="w-full bg-gray-700 rounded-full h-2">
                      <div
                        className={`h-2 rounded-full ${
                          course.matchPercentage < 30
                            ? 'bg-red-500'
                            : course.matchPercentage < 50
                            ? 'bg-yellow-500'
                            : 'bg-orange-500'
                        }`}
                        style={{ width: `${course.matchPercentage}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
