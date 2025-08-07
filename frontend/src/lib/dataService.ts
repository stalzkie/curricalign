// Mock data service - replace with actual API calls to FastAPI backend
export interface Skill {
  name: string;
  demand: number;
}

export interface Course {
  courseName: string;
  courseCode: string;
  matchPercentage: number;
}

export interface Job {
  title: string;
  demand: number;
}

export interface KPIData {
  averageAlignmentScore: number;
  totalSubjectsAnalyzed: number;
  totalJobPostsAnalyzed: number;
  skillsExtracted: number;
}

// Mock data - replace with actual API calls
export const mockSkillsData: Skill[] = [
  { name: 'JavaScript', demand: 85 },
  { name: 'Python', demand: 82 },
  { name: 'React', demand: 78 },
  { name: 'SQL', demand: 75 },
  { name: 'Node.js', demand: 70 },
  { name: 'Java', demand: 68 },
  { name: 'Machine Learning', demand: 65 },
  { name: 'AWS', demand: 62 },
  { name: 'Data Analysis', demand: 60 },
  { name: 'Docker', demand: 58 },
  { name: 'Others', demand: 120 }
];

export const mockCoursesData: Course[] = [
  { courseName: 'Advanced Web Development', courseCode: 'CS-401', matchPercentage: 92 },
  { courseName: 'Data Structures & Algorithms', courseCode: 'CS-301', matchPercentage: 88 },
  { courseName: 'Database Management Systems', courseCode: 'CS-302', matchPercentage: 85 },
  { courseName: 'Software Engineering', courseCode: 'CS-403', matchPercentage: 83 },
  { courseName: 'Machine Learning Fundamentals', courseCode: 'CS-501', matchPercentage: 81 },
  { courseName: 'Cloud Computing', courseCode: 'CS-502', matchPercentage: 79 },
  { courseName: 'Mobile App Development', courseCode: 'CS-404', matchPercentage: 77 },
  { courseName: 'Cybersecurity Basics', courseCode: 'CS-503', matchPercentage: 75 }
];

export const mockJobsData: Job[] = [
  { title: 'Software Developer', demand: 25 },
  { title: 'Data Scientist', demand: 18 },
  { title: 'Full Stack Developer', demand: 15 },
  { title: 'DevOps Engineer', demand: 12 },
  { title: 'ML Engineer', demand: 10 },
  { title: 'Product Manager', demand: 8 },
  { title: 'UI/UX Designer', demand: 7 },
  { title: 'QA Engineer', demand: 5 },
  { title: 'Others', demand: 15 }
];

export const mockMissingSkills: string[] = [
  'Kubernetes',
  'GraphQL',
  'TypeScript',
  'Redis',
  'Microservices',
  'Blockchain',
  'Vue.js',
  'Angular',
  'MongoDB',
  'Jenkins',
  'Terraform',
  'Elasticsearch'
];

export const mockCourseWarnings: Course[] = [
  { courseName: 'Introduction to COBOL', courseCode: 'CS-201', matchPercentage: 35 },
  { courseName: 'Assembly Language Programming', courseCode: 'CS-202', matchPercentage: 42 },
  { courseName: 'Desktop Publishing', courseCode: 'CS-203', matchPercentage: 38 },
  { courseName: 'Legacy System Maintenance', courseCode: 'CS-204', matchPercentage: 45 }
];

export const mockKPIData: KPIData = {
  averageAlignmentScore: 76.8,
  totalSubjectsAnalyzed: 127,
  totalJobPostsAnalyzed: 2459,
  skillsExtracted: 342
};

// Future API functions to implement with FastAPI backend
export async function fetchMostInDemandSkills(): Promise<Skill[]> {
  // TODO: Replace with actual API call
  // return await fetch('/api/skills/most-demanded').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockSkillsData), 1000);
  });
}

export async function fetchTopMatchingCourses(): Promise<Course[]> {
  // TODO: Replace with actual API call
  // return await fetch('/api/courses/top-matching').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockCoursesData), 1000);
  });
}

export async function fetchInDemandJobs(): Promise<Job[]> {
  // TODO: Replace with actual API call
  // return await fetch('/api/jobs/in-demand').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockJobsData), 1000);
  });
}

export async function fetchMissingSkills(): Promise<string[]> {
  // TODO: Replace with actual API call
  // return await fetch('/api/skills/missing').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockMissingSkills), 1000);
  });
}

export async function fetchCourseWarnings(): Promise<Course[]> {
  // TODO: Replace with actual API call
  // return await fetch('/api/courses/warnings').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockCourseWarnings), 1000);
  });
}

export async function fetchKPIData(): Promise<KPIData> {
  // TODO: Replace with actual API call
  // return await fetch('/api/dashboard/kpi').then(res => res.json());
  return new Promise(resolve => {
    setTimeout(() => resolve(mockKPIData), 1000);
  });
}
