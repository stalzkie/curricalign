// components/dashboard/Dashboard.tsx
'use client';

import KPIContainer from './containers/KPIContainer';
import MostInDemandSkillsContainer from './containers/MostInDemandSkillsContainer';
import InDemandJobsContainer from './containers/InDemandJobsContainer';
import CourseWarningsContainer from './containers/CourseWarningsContainer';
import TopCoursesContainer from './containers/TopCoursesContainer';
import MissingSkillsContainer from './containers/MissingSkillsContainer';

export default function Dashboard() {
  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-7xl mx-auto">
        <div className="mb-6 flex items-center justify-between gap-4">
          <h1 className="text-2xl font-bold text_defaultColor">Dashboard</h1>
        </div>

        {/* KPI Cards */}
        <KPIContainer />

        {/* Row 1: Most In-Demand Skills (full width) */}
        <div className="mt-8">
          <MostInDemandSkillsContainer />
        </div>

        {/* Row 2: In-Demand Jobs & Course Warnings */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
          <InDemandJobsContainer />
          <CourseWarningsContainer />
        </div>

        {/* Row 3: Top Matching Courses & Missing Skills */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-8 items-start">
          <div className="lg:col-span-2">
            <TopCoursesContainer />
          </div>
          <MissingSkillsContainer />
        </div>
      </div>
    </div>
  );
}
