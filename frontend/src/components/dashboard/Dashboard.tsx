'use client';

import { useState, useEffect } from 'react';
import KPICard from './KPICard';
import SkillsBarChart from './SkillsBarChart';
import JobsPieChart from './JobsPieChart';
import TopCoursesTable from './TopCoursesTable';
import MissingSkillsList from './MissingSkillsList';
import CourseWarningsList from './CourseWarningsList';
import {
  fetchMostInDemandSkills,
  fetchTopMatchingCourses,
  fetchInDemandJobs,
  fetchMissingSkills,
  fetchCourseWarnings,
  fetchKPIData,
  type Skill,
  type Course,
  type Job,
  type KPIData
} from '../../lib/dataService';

import {
  RiDonutChartLine,    // Average Alignment Score
  RiBookOpenLine,      // Total Subjects
  RiBriefcaseLine,     // Total Job Posts
  RiStackLine          // Skills Extracted
} from 'react-icons/ri';

export default function Dashboard() {
  const [skillsData, setSkillsData] = useState<Skill[]>([]);
  const [coursesData, setCoursesData] = useState<Course[]>([]);
  const [jobsData, setJobsData] = useState<Job[]>([]);
  const [missingSkills, setMissingSkills] = useState<string[]>([]);
  const [courseWarnings, setCourseWarnings] = useState<Course[]>([]);
  const [kpiData, setKpiData] = useState<KPIData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadDashboardData = async () => {
      setLoading(true);
      try {
        const [skills, courses, jobs, missing, warnings, kpi] = await Promise.all([
          fetchMostInDemandSkills(),
          fetchTopMatchingCourses(),
          fetchInDemandJobs(),
          fetchMissingSkills(),
          fetchCourseWarnings(),
          fetchKPIData()
        ]);

        setSkillsData(skills);
        setCoursesData(courses);
        setJobsData(jobs);
        setMissingSkills(missing);
        setCourseWarnings(warnings);
        setKpiData(kpi);
      } catch (error) {
        console.error('Error loading dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    loadDashboardData();
  }, []);

  if (loading) {
    return (
      <div className="p-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <div
                className="animate-spin rounded-full h-12 w-12 mx-auto mb-4"
                style={{
                  borderBottom: '2px solid var(--brand-teal, #025864)',
                  borderLeft: '2px solid transparent',
                  borderRight: '2px solid transparent',
                  borderTop: '2px solid transparent',
                }}
              />
              <p className="text_secondaryColor">Loading dashboard data...</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 min-h-screen" style={{ background: 'var(--background)' }}>
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text_defaultColor mb-8">Dashboard</h1>

        {/* KPI Cards */}
        {kpiData && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <KPICard
              title="Average Alignment Score"
              value={`${kpiData.averageAlignmentScore}%`}
              icon={<RiDonutChartLine />}
            />
            <KPICard
              title="Total Subjects Analyzed"
              value={kpiData.totalSubjectsAnalyzed.toLocaleString()}
              icon={<RiBookOpenLine />}
            />
            <KPICard
              title="Total Job Posts Analyzed"
              value={kpiData.totalJobPostsAnalyzed.toLocaleString()}
              icon={<RiBriefcaseLine />}
            />
            <KPICard
              title="Skills Extracted"
              value={kpiData.skillsExtracted.toLocaleString()}
              icon={<RiStackLine />}
            />
          </div>
        )}

        {/* Row 1: Most In-Demand Skills (full width) */}
        <div className="mb-8">
          <SkillsBarChart data={skillsData} />
        </div>

        {/* Row 2: In-Demand Jobs & Course Warnings */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          <JobsPieChart data={jobsData} />
          <CourseWarningsList data={courseWarnings} />
        </div>

        {/* Row 3: Top Matching Courses & Missing Skills */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8 items-start">
          <div className="lg:col-span-2 min-h-0">
            <TopCoursesTable data={coursesData} />
          </div>
          <div className="min-h-0 flex">
            <MissingSkillsList data={missingSkills} />
          </div>
        </div>
      </div>
    </div>
  );
}
