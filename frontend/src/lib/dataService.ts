// src/lib/dataService.ts
// TYPES
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

export interface MissingSkill {
  skill: string;
  count: number;
}

const BASE_URL = "/api/dashboard";
const VERSION_URL = "/api/dashboard/version";

// 🔗 Version-based cache utilities
import {
  getWithVersionCache,
  getLastChangedFromCache,
  formatLastChanged,
  clearCache,
  clearMany,
  setCache,
} from "./dataCache";

// Cache keys per resource (localStorage)
const CK = {
  skills: "dash:skills",
  topCourses: "dash:top-courses",
  jobs: "dash:jobs",
  missingSkills: "dash:missing-skills",
  warnings: "dash:warnings",
  kpi: "dash:kpi",
} as const;

// Public helpers for the banner
export function getLastChangedISOFromAnyCache(): string | null {
  return (
    getLastChangedFromCache(CK.kpi) ||
    getLastChangedFromCache(CK.skills) ||
    getLastChangedFromCache(CK.topCourses) ||
    getLastChangedFromCache(CK.jobs) ||
    getLastChangedFromCache(CK.missingSkills) ||
    getLastChangedFromCache(CK.warnings) ||
    null
  );
}

export function getRecentlyUpdatedLabel(): string {
  const iso = getLastChangedISOFromAnyCache();
  return iso ? `Recently updated on ${formatLastChanged(iso)}` : "";
}

// Optional: expose invalidation utilities if you want to manually force-refresh from UI
export const invalidateAllDashboardCaches = () => clearMany(Object.values(CK));
export const invalidateKpiCache = () => clearCache(CK.kpi);

// ===============================
// Data fetchers (version-cached)
// ===============================

// 1) Most In-Demand Skills
export async function fetchMostInDemandSkills(
  signal?: AbortSignal
): Promise<Skill[]> {
  try {
    const { data } = await getWithVersionCache<Skill[]>(
      CK.skills,
      `${BASE_URL}/skills`,
      VERSION_URL,
      signal
    );

    return (data ?? [])
      .filter((s) => s?.name && s.name.trim() !== "")
      .sort((a, b) => Number(b?.demand ?? 0) - Number(a?.demand ?? 0));
  } catch (error: any) {
    if (error?.name === "AbortError") return [];
    console.error("❌ Failed to fetch in-demand skills:", error);
    return [];
  }
}

// 2) Top Matching Courses
export async function fetchTopMatchingCourses(
  signal?: AbortSignal
): Promise<Course[]> {
  try {
    const { data } = await getWithVersionCache<any[]>(
      CK.topCourses,
      `${BASE_URL}/top-courses`,
      VERSION_URL,
      signal
    );

    return Array.isArray(data)
      ? data.map((item) => ({
          courseName: item?.courseName || "Unknown Course",
          courseCode: item?.courseCode || "N/A",
          matchPercentage: Number(item?.matchPercentage) || 0,
        }))
      : [];
  } catch (error: any) {
    if (error?.name === "AbortError") return [];
    console.error("❌ Failed to fetch top courses:", error);
    return [];
  }
}

// 3) In-Demand Job Titles (Top 10)
export async function fetchInDemandJobs(
  signal?: AbortSignal
): Promise<Job[]> {
  try {
    const { data } = await getWithVersionCache<any[]>(
      CK.jobs,
      `${BASE_URL}/jobs`,
      VERSION_URL,
      signal
    );

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
    if (error?.name === "AbortError") return [];
    console.error("❌ Failed to fetch in-demand jobs:", error);
    return [];
  }
}

// 4) Missing Skills (string[] for existing UI)
export async function fetchMissingSkills(
  signal?: AbortSignal,
  minThreshold?: number 
): Promise<string[]> {
  try {
    const minQuery = minThreshold ? `min=${minThreshold}` : '';
    // --- START TEMPORARY CACHE BUSTER ---
    // This is added to force a cache bypass if an external CDN/Proxy is intercepting the request.
    const cacheBuster = `cb=${Date.now()}`;
    const separator = minQuery ? '&' : '?';
    
    // Construct the URL with minThreshold and the cache buster
    const url = `${BASE_URL}/missing-skills${separator}${minQuery}${minQuery ? '&' : ''}${cacheBuster}`; 
    // --- END TEMPORARY CACHE BUSTER ---
      
    // The API now returns [{ skill, count }, ...] from evaluator output.
    const { data } = await getWithVersionCache<any>(
      CK.missingSkills,
      url, // <-- This unique URL will bypass the CDN cache
      VERSION_URL,
      signal
    );

    if (!Array.isArray(data)) return [];

    // Filter to ensure we only proceed if we have the new, preferred object shape
    if (data.length > 0 && typeof data[0] === "object" && "skill" in data[0] && "count" in data[0]) {
      const arr = (data as MissingSkill[])
        .filter((d) => d?.skill && typeof d.skill === "string")
        .sort((a, b) => Number(b?.count ?? 0) - Number(a?.count ?? 0))
        .map((d) => d.skill.toLowerCase().trim());
      
      // de-dup while preserving order
      const seen = new Set<string>();
      const out: string[] = [];
      for (const s of arr) {
        if (!seen.has(s)) {
          seen.add(s);
          out.push(s);
        }
      }
      return out;
    }

    // Fallback/Legacy shapes: array of strings or arrays of strings/CSV (kept for robustness)
    const unique = new Set<string>();
    for (const entry of data) {
      if (Array.isArray(entry)) {
        entry
          .map((s) => String(s))
          .forEach((s) => unique.add(s.trim().toLowerCase()));
      } else if (typeof entry === "string") {
        entry
          .split(",")
          .map((s) => s.trim().toLowerCase())
          .filter(Boolean)
          .forEach((s) => unique.add(s));
      } else if (entry && typeof entry === "object" && "name" in entry) {
        // ultra-legacy: objects like { name: "python" }
        const n = String((entry as any).name || "").trim().toLowerCase();
        if (n) unique.add(n);
      }
    }
    return Array.from(unique).sort();
  } catch (error: any) {
    if (error?.name === "AbortError") return [];
    // ❌ Error logging retained for debugging
    console.error("❌ Failed to fetch missing skills:", error); 
    return [];
  }
}

// Optional: Missing skills WITH counts (useful for richer UI)
export async function fetchMissingSkillsWithCounts(
  signal?: AbortSignal,
  minThreshold?: number 
): Promise<MissingSkill[]> {
  try {
    const minQuery = minThreshold ? `min=${minThreshold}` : '';
    // --- START TEMPORARY CACHE BUSTER ---
    const cacheBuster = `cb=${Date.now()}`;
    const separator = minQuery ? '&' : '?';
    
    const url = `${BASE_URL}/missing-skills${separator}${minQuery}${minQuery ? '&' : ''}${cacheBuster}`; 
    // --- END TEMPORARY CACHE BUSTER ---

    const { data } = await getWithVersionCache<any[]>(
      CK.missingSkills,
      url, // <-- This unique URL will bypass the CDN cache
      VERSION_URL,
      signal
    );

    if (!Array.isArray(data)) return [];

    if (data.length > 0 && typeof data[0] === "object" && "skill" in data[0] && "count" in data[0]) {
      // Preferred new shape
      return (data as MissingSkill[])
        .filter((d) => d?.skill)
        .map((d) => ({ skill: String(d.skill), count: Number(d.count) || 0 }))
        .sort((a, b) => b.count - a.count);
    }

    // Fallback: derive counts from legacy formats (count = 1 per occurrence)
    const counts = new Map<string, number>();
    for (const entry of data) {
      const push = (v: string) => {
        const key = v.trim().toLowerCase();
        if (!key) return;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      };
      if (Array.isArray(entry)) {
        entry.forEach((s) => push(String(s)));
      } else if (typeof entry === "string") {
        entry.split(",").forEach((s) => push(s));
      } else if (entry && typeof entry === "object" && "name" in entry) {
        push(String((entry as any).name || ""));
      }
    }
    return Array.from(counts.entries())
      .map(([skill, count]) => ({ skill, count }))
      .sort((a, b) => b.count - a.count);
  } catch (error: any) {
    if (error?.name === "AbortError") return [];
    console.error("❌ Failed to fetch missing skills (with counts):", error);
    return [];
  }
}

// 5) Course Warnings
export async function fetchCourseWarnings(
  signal?: AbortSignal
): Promise<Course[]> {
  try {
    const { data } = await getWithVersionCache<any[]>(
      CK.warnings,
      `${BASE_URL}/warnings`,
      VERSION_URL,
      signal
    );

    return Array.isArray(data)
      ? data.map((item) => ({
          courseName: item?.courseName || "Unknown Course",
          courseCode: item?.courseCode || "N/A",
          matchPercentage: Number(item?.matchPercentage) || 0,
        }))
      : [];
  } catch (error: any) {
    if (error?.name === "AbortError") return [];
    console.error("❌ Failed to fetch course warnings:", error);
    return [];
  }
}

// 6) KPI Data
export async function fetchKPIData(
  signal?: AbortSignal
): Promise<KPIData> {
  try {
    const { data } = await getWithVersionCache<any>(
      CK.kpi,
      `${BASE_URL}/kpi`,
      VERSION_URL,
      signal
    );

    return {
      averageAlignmentScore: Number(data?.averageAlignmentScore) || 0,
      totalSubjectsAnalyzed: Number(data?.totalSubjectsAnalyzed) || 0,
      totalJobPostsAnalyzed: Number(data?.totalJobPostsAnalyzed) || 0,
      skillsExtracted: Number(data?.skillsExtracted) || 0,
    };
  } catch (error: any) {
    if (error?.name === "AbortError") {
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

// ===============================
// Alias Exports (for container compatibility)
// ===============================

// Skills
export const getMostInDemandSkills = fetchMostInDemandSkills;
export const getTopSkills = fetchMostInDemandSkills;
export const fetchTopSkills = fetchMostInDemandSkills;

// Top courses table
export const getTopMatchingCourses = fetchTopMatchingCourses;
export const getTopCourses = fetchTopMatchingCourses;
export const fetchTopCourses = fetchTopMatchingCourses;

// In-demand jobs
export const getInDemandJobs = fetchInDemandJobs;

// Missing skills list
export const getMissingSkills = fetchMissingSkills;
export const loadMissingSkills = fetchMissingSkills;

// Course warnings
export const getCourseWarnings = fetchCourseWarnings;

// Optional re-exports if needed elsewhere
export { setCache, clearCache, clearMany } from "./dataCache";