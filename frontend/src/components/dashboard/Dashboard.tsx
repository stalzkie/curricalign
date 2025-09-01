// components/dashboard/Dashboard.tsx
'use client';

import { useEffect, useState } from 'react';

import KPIContainer from './containers/KPIContainer';
import MostInDemandSkillsContainer from './containers/MostInDemandSkillsContainer';
import InDemandJobsContainer from './containers/InDemandJobsContainer';
import CourseWarningsContainer from './containers/CourseWarningsContainer';
import TopCoursesContainer from './containers/TopCoursesContainer';
import MissingSkillsContainer from './containers/MissingSkillsContainer';
import UpdateBadge from './UpdateBadge';

// 🔎 listens to /api/dashboard/version (ETag/304) and returns the latest ISO string
import { useVersionWatcher } from '@/lib/useVersionWatcher';

export default function Dashboard() {
  // Prevent hydration flicker by rendering only after client mounts
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // When this ISO changes, we know backend data changed.
  const versionIso = useVersionWatcher();

  // A stable key for each section; when version changes, React remounts the section,
  // causing its useEffect data-fetch to run again (and hit the version-cached APIs).
  const keySuffix = versionIso ?? 'init';

  if (!mounted) return null;

  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-7xl mx-auto">
        <div className="mb-6 flex items-center justify-between gap-4">
          <h1 className="text-2xl font-bold text_defaultColor">Dashboard</h1>
          <UpdateBadge tableName="" />
        </div>

        {/* KPI Cards */}
        <KPIContainer key={`kpi-${keySuffix}`} />

        {/* Row 1: Most In-Demand Skills (full width) */}
        <div className="mt-8">
          <MostInDemandSkillsContainer key={`skills-${keySuffix}`} />
        </div>

        {/* Row 2: In-Demand Jobs & Course Warnings */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
          <InDemandJobsContainer key={`jobs-${keySuffix}`} />
          <CourseWarningsContainer key={`warnings-${keySuffix}`} />
        </div>

        {/* Row 3: Top Matching Courses & Missing Skills */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-8 items-start">
          <div className="lg:col-span-2">
            <TopCoursesContainer key={`topcourses-${keySuffix}`} />
          </div>
          <MissingSkillsContainer key={`missingskills-${keySuffix}`} />
        </div>
      </div>
    </div>
  );
}
