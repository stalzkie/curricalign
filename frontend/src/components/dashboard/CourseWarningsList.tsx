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
  const GAP_Y = 12;

  const shouldScroll = data.length > TARGET;

  useEffect(() => {
    if (firstItemRef.current) {
      const h = firstItemRef.current.getBoundingClientRect().height;
      if (h > 0) setItemHeight(h);
    } else {
      setItemHeight(null);
    }
  }, [data]);

  const maxHeight = useMemo(() => {
    if (!itemHeight || !shouldScroll) return undefined;
    return itemHeight * TARGET + GAP_Y * (TARGET - 1);
  }, [itemHeight, shouldScroll]);

  // Map to global.css classes
  const getWarningLevel = (p: number) => {
    if (p < 30) return { textClass: 'critical-text', bgClass: 'critical-bg', barClass: 'progress-bar-critical', level: 'Critical' };
    if (p < 50) return { textClass: 'warning-text',  bgClass: 'warning-bg',  barClass: 'progress-bar-warning',  level: 'Warning'  };
    return          { textClass: 'lowmatch-text',   bgClass: 'lowmatch-bg', barClass: 'progress-bar-lowmatch', level: 'Low Match' };
  };

  return (
    <div className="btn_border_silver overflow-hidden">
      <div className="card_background rounded p-6 flex flex-col">
        <h3 className="text-xl font-bold text_defaultColor mb-4">Course Warnings</h3>

        <div
          className={`${shouldScroll ? 'overflow-y-auto scrollbar-thin' : 'overflow-visible'} min-h-0`}
          style={maxHeight ? { maxHeight } : undefined}
        >
          <div className="space-y-3">
            {data.map((course, index) => {
              const warning = getWarningLevel(course.matchPercentage);
              return (
                <div
                  key={index}
                  ref={index === 0 ? firstItemRef : null}
                  className={`warning-card ${warning.bgClass}`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h4 className="text_defaultColor font-semibold text-sm">{course.courseName}</h4>
                      <p className="text_secondaryColor text-xs mt-1">{course.courseCode}</p>
                    </div>
                    <div className="text-right ml-4">
                      <div className={`text-lg font-bold ${warning.textClass}`}>{course.matchPercentage}%</div>
                      <div className={`text-xs ${warning.textClass}`}>{warning.level}</div>
                    </div>
                  </div>
                  <div className="mt-3">
                    <div className="progress-track">
                      <div
                        className={`h-2 rounded-full ${warning.barClass}`}
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
