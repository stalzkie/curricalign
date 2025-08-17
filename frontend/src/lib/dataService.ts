// lib/dataService.ts

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

// ---- Shared fetcher with retry + AbortSignal ----
async function fetchJSON<T>(
  url: string,
  init?: RequestInit,
  signal?: AbortSignal,
  retries = 3,
  retryDelay = 300
): Promise<T> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        ...init,
        signal,
        cache: "no-store",
        headers: {
          ...(init?.headers ?? {}),
          Accept: "application/json",
        },
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`GET ${url} failed: ${res.status} ${text}`);
      }
      return res.json() as Promise<T>;
    } catch (error: any) {
      if (error.name === "AbortError") throw error;
      if (attempt === retries) throw error;
      await new Promise((res) => setTimeout(res, retryDelay));
    }
  }
  throw new Error(`Failed to fetch ${url}`);
}

// === 1. Most In-Demand Skills ===
export async function fetchMostInDemandSkills(signal?: AbortSignal): Promise<Skill[]> {
  try {
    const rawSkills = await fetchJSON<Skill[]>(`${BASE_URL}/skills`, undefined, signal);
    return (rawSkills ?? [])
      .filter((s) => s?.name && s.name.trim() !== "")
      .sort((a, b) => Number(b?.demand ?? 0) - Number(a?.demand ?? 0));
  } catch (error: any) {
    if (error.name === "AbortError") return [];
    console.error("❌ Failed to fetch in-demand skills:", error);
    return [];
  }
}

// === 2. Top Matching Courses ===
export async function fetchTopMatchingCourses(signal?: AbortSignal): Promise<Course[]> {
  try {
    const data = await fetchJSON<any[]>(`${BASE_URL}/top-courses`, undefined, signal);
    return Array.isArray(data)
      ? data.map((item) => ({
          courseName: item?.courseName || "Unknown Course",
          courseCode: item?.courseCode || "N/A",
          matchPercentage: Number(item?.matchPercentage) || 0,
        }))
      : [];
  } catch (error: any) {
    if (error.name === "AbortError") return [];
    console.error("❌ Failed to fetch top courses:", error);
    return [];
  }
}

// === 3. In-Demand Job Titles (Top 10) ===
export async function fetchInDemandJobs(signal?: AbortSignal): Promise<Job[]> {
  try {
    const data = await fetchJSON<any[]>(`${BASE_URL}/jobs`, undefined, signal);
    return Array.isArray(data)
      ? data
          .filter((item) => item?.title && String(item.title).trim() !== "")
          .sort((a, b) => Number(b?.demand ?? 0) - Number(a?.demand ?? 0))
          .slice(0, 10)
          .map((item) => ({
            title: String(item.title),
            demand: Number(item.demand) || 0,
          }))
      : [];
  } catch (error: any) {
    if (error.name === "AbortError") return [];
    console.error("❌ Failed to fetch in-demand jobs:", error);
    return [];
  }
}

// === 4. Missing Skills ===
export async function fetchMissingSkills(signal?: AbortSignal): Promise<string[]> {
  try {
    const rawSkills = await fetchJSON<(string | string[])[]>(
      `${BASE_URL}/missing-skills`,
      undefined,
      signal
    );
    const unique = new Set<string>();
    for (const entry of rawSkills ?? []) {
      if (Array.isArray(entry)) {
        entry.map((s) => String(s)).forEach((s) => unique.add(s.trim().toLowerCase()));
      } else if (typeof entry === "string") {
        entry
          .split(",")
          .map((s) => s.trim().toLowerCase())
          .filter(Boolean)
          .forEach((s) => unique.add(s));
      }
    }
    return Array.from(unique).sort();
  } catch (error: any) {
    if (error.name === "AbortError") return [];
    console.error("❌ Failed to fetch missing skills:", error);
    return [];
  }
}

// === 5. Course Warnings ===
export async function fetchCourseWarnings(signal?: AbortSignal): Promise<Course[]> {
  try {
    const data = await fetchJSON<any[]>(`${BASE_URL}/warnings`, undefined, signal);
    return Array.isArray(data)
      ? data.map((item) => ({
          courseName: item?.courseName || "Unknown Course",
          courseCode: item?.courseCode || "N/A",
          matchPercentage: Number(item?.matchPercentage) || 0,
        }))
      : [];
  } catch (error: any) {
    if (error.name === "AbortError") return [];
    console.error("❌ Failed to fetch course warnings:", error);
    return [];
  }
}

// === 6. KPI Data ===
export async function fetchKPIData(signal?: AbortSignal): Promise<KPIData> {
  try {
    const data = await fetchJSON<any>(`${BASE_URL}/kpi`, undefined, signal);
    return {
      averageAlignmentScore: Number(data?.averageAlignmentScore) || 0,
      totalSubjectsAnalyzed: Number(data?.totalSubjectsAnalyzed) || 0,
      totalJobPostsAnalyzed: Number(data?.totalJobPostsAnalyzed) || 0,
      skillsExtracted: Number(data?.skillsExtracted) || 0,
    };
  } catch (error: any) {
    if (error.name === "AbortError") {
      return {
        averageAlignmentScore: 0,
        totalSubjectsAnalyzed: 0,
        totalJobPostsAnalyzed: 0,
        skillsExtracted: 0,
      };
    }
    console.error("❌ FastAPI KPI fetch failed:", error);
    return {
      averageAlignmentScore: 0,
      totalSubjectsAnalyzed: 0,
      totalJobPostsAnalyzed: 0,
      skillsExtracted: 0,
    };
  }
}

// ================= Alias Exports (for container compatibility) =============

// Skills (bar chart)
export const getMostInDemandSkills = fetchMostInDemandSkills;
export const getTopSkills = fetchMostInDemandSkills;
export const fetchTopSkills = fetchMostInDemandSkills;

// Top courses table
export const getTopMatchingCourses = fetchTopMatchingCourses;
export const getTopCourses = fetchTopMatchingCourses;
export const fetchTopCourses = fetchTopMatchingCourses;

// In-demand jobs (pie)
export const getInDemandJobs = fetchInDemandJobs;

// Missing skills list
export const getMissingSkills = fetchMissingSkills;
export const loadMissingSkills = fetchMissingSkills;

// Course warnings
export const getCourseWarnings = fetchCourseWarnings;
