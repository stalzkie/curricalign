// === TYPES ===
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

const BASE_URL = "/api/dashboard";

// === 1. Most In-Demand Skills ===
export async function fetchMostInDemandSkills(): Promise<Skill[]> {
  try {
    const response = await fetch(`${BASE_URL}/skills`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const rawSkills: Skill[] = await response.json();

    return rawSkills
      .filter((s) => s.name && s.name.trim() !== "")
      .sort((a, b) => b.demand - a.demand);
  } catch (error) {
    console.error("❌ Failed to fetch in-demand skills:", error);
    return [];
  }
}

// === 2. Top Matching Courses ===
export async function fetchTopMatchingCourses(): Promise<Course[]> {
  try {
    const response = await fetch(`${BASE_URL}/top-courses`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    return Array.isArray(data)
      ? data.map((item: any) => ({
          courseName: item.courseName || "Unknown Course",
          courseCode: item.courseCode || "N/A",
          matchPercentage: item.matchPercentage || 0,
        }))
      : [];
  } catch (error) {
    console.error("❌ Failed to fetch top courses:", error);
    return [];
  }
}

// === 3. In-Demand Job Titles (Top 10) ===
export async function fetchInDemandJobs(): Promise<Job[]> {
  try {
    const response = await fetch(`${BASE_URL}/jobs`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const data = await response.json();

    return Array.isArray(data)
      ? data
          .filter((item: any) => item.title && item.title.trim() !== "")
          .sort((a, b) => b.demand - a.demand)
          .slice(0, 10)
          .map((item: any) => ({
            title: item.title,
            demand: item.demand,
          }))
      : [];
  } catch (error) {
    console.error("❌ Failed to fetch in-demand jobs:", error);
    return [];
  }
}

// === 4. Missing Skills ===
export async function fetchMissingSkills(): Promise<string[]> {
  try {
    const response = await fetch(`${BASE_URL}/missing-skills`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const rawSkills: string[] = await response.json();

    const uniqueSet = new Set<string>();
    for (const entry of rawSkills) {
      if (typeof entry === "string") {
        const skills = entry
          .split(",")
          .map((s) => s.trim().toLowerCase())
          .filter(Boolean);
        for (const skill of skills) {
          uniqueSet.add(skill);
        }
      }
    }

    return Array.from(uniqueSet).sort();
  } catch (error) {
    console.error("❌ Failed to fetch missing skills:", error);
    return [];
  }
}

// === 5. Course Warnings ===
export async function fetchCourseWarnings(): Promise<Course[]> {
  try {
    const response = await fetch(`${BASE_URL}/warnings`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    return Array.isArray(data)
      ? data.map((item: any) => ({
          courseName: item.courseName || "Unknown Course",
          courseCode: item.courseCode || "N/A",
          matchPercentage: item.matchPercentage || 0,
        }))
      : [];
  } catch (error) {
    console.error("❌ Failed to fetch course warnings:", error);
    return [];
  }
}

// === 6. KPI Data ===
export async function fetchKPIData(): Promise<KPIData> {
  try {
    const response = await fetch(`${BASE_URL}/kpi`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API error ${response.status}: ${errorText}`);
    }

    const data = await response.json();
    return {
      averageAlignmentScore: data.averageAlignmentScore || 0,
      totalSubjectsAnalyzed: data.totalSubjectsAnalyzed || 0,
      totalJobPostsAnalyzed: data.totalJobPostsAnalyzed || 0,
      skillsExtracted: data.skillsExtracted || 0,
    };
  } catch (error) {
    console.error("❌ FastAPI KPI fetch failed:", error);
    return {
      averageAlignmentScore: 0,
      totalSubjectsAnalyzed: 0,
      totalJobPostsAnalyzed: 0,
      skillsExtracted: 0,
    };
  }
}
