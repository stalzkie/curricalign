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
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500 mx-auto mb-4"></div>
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
        <h1 className="text-4xl font-bold text_defaultColor mb-8">Dashboard</h1>
        
        {/* KPI Cards */}
        {kpiData && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <KPICard
              title="Average Alignment Score"
              value={`${kpiData.averageAlignmentScore}%`}
              icon=" "
            />
            <KPICard
              title="Total Subjects Analyzed"
              value={kpiData.totalSubjectsAnalyzed.toLocaleString()}
              icon=" "
            />
            <KPICard
              title="Total Job Posts Analyzed"
              value={kpiData.totalJobPostsAnalyzed.toLocaleString()}
              icon=" "
            />
            <KPICard
              title="Skills Extracted"
              value={kpiData.skillsExtracted.toLocaleString()}
              icon=" "
            />
          </div>
        )}

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          <SkillsBarChart data={skillsData} />
          <JobsPieChart data={jobsData} />
        </div>

        {/* Table and Lists Row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8 items-start">
          <div className="lg:col-span-2 min-h-0">
            <TopCoursesTable data={coursesData} />
          </div>
          <div className="min-h-0 flex">
            <MissingSkillsList data={missingSkills} />
          </div>
        </div>
        
        {/* Course Warnings */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <CourseWarningsList data={courseWarnings} />
          
          {/* Additional insights card */}
          {/* <div className="btn_border_silver">
            <div className="card_background rounded p-6">
              <h3 className="text-xl font-bold text_defaultColor mb-4">Quick Insights</h3>
              <div className="space-y-4">
                <div className="p-4 bg-gray-800/50 rounded-lg">
                  <h4 className="text-green-400 font-semibold text-sm mb-2">✅ Strong Alignment Areas</h4>
                  <p className="text_triaryColor text-sm">Web development and database management courses show excellent job market alignment.</p>
                </div>
                <div className="p-4 bg-gray-800/50 rounded-lg">
                  <h4 className="text-yellow-400 font-semibold text-sm mb-2">⚠️ Improvement Opportunities</h4>
                  <p className="text_triaryColor text-sm">Consider adding more cloud computing and DevOps content to existing courses.</p>
                </div>
                <div className="p-4 bg-gray-800/50 rounded-lg">
                  <h4 className="text-red-400 font-semibold text-sm mb-2">🔄 Curriculum Updates Needed</h4>
                  <p className="text_triaryColor text-sm">Legacy technology courses need modernization or replacement.</p>
                </div>
              </div>
            </div>
          </div> */}
        </div>
      </div>
    </div>
  );
}
