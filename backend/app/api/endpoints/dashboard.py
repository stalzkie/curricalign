from fastapi import APIRouter, HTTPException
from ...core.supabase_client import supabase
from typing import List, Dict

router = APIRouter()

@router.get("/dashboard/skills")
def get_in_demand_skills():
    try:
        response = supabase.from_("job_skills").select("job_skills").execute()
        data = response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    frequency: Dict[str, int] = {}
    for record in data:
        skills = record.get("job_skills", "")
        for skill in [s.strip().lower() for s in skills.split(",") if s.strip()]:
            frequency[skill] = frequency.get(skill, 0) + 1

    sorted_skills = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "demand": demand} for name, demand in sorted_skills]

@router.get("/dashboard/top-courses")
def get_top_courses():
    try:
        response = supabase.from_("course_alignment_scores") \
            .select("course_title, course_code, score, calculated_at") \
            .order("score", desc=True).execute()
        records = response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching top courses: {str(e)}")

    if not records:
        return []

    latest_batch = max(r["calculated_at"] for r in records if r.get("calculated_at"))
    recent_records = [r for r in records if r.get("calculated_at") == latest_batch]

    return [
        {
            "courseName": r["course_title"] or "Unknown Course",
            "courseCode": r["course_code"] or "N/A",
            "matchPercentage": r["score"] or 0
        }
        for r in recent_records
    ]

@router.get("/dashboard/jobs")
def get_trending_jobs():
    try:
        response = supabase.from_("trending_jobs").select("title, trending_score") \
            .order("trending_score", desc=True).execute()
        records = response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trending jobs: {str(e)}")

    return [{"title": r["title"], "demand": r["trending_score"]} for r in records if r["title"]]

@router.get("/dashboard/missing-skills")
def get_missing_skills():
    try:
        job_response = supabase.from_("job_skills").select("job_skills").execute()
        course_response = supabase.from_("course_skills").select("course_skills").execute()
        job_data = job_response.data
        course_data = course_response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    job_skills_set = set()
    for record in job_data:
        skills = record.get("job_skills", "")
        for skill in [s.strip().lower() for s in skills.split(",") if s.strip()]:
            job_skills_set.add(skill)

    course_skills_set = set()
    for record in course_data:
        skills = record.get("course_skills", [])
        if isinstance(skills, list):
            for skill in skills:
                course_skills_set.add(skill.strip().lower())

    missing = list(job_skills_set - course_skills_set)
    return missing

@router.get("/dashboard/warnings")
def get_low_scoring_courses():
    try:
        response = supabase.from_("course_alignment_scores") \
            .select("course_title, course_code, score, calculated_at") \
            .lte("score", 50).order("score", desc=False).execute()
        records = response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching warnings: {str(e)}")

    if not records:
        return []

    latest_batch = max(r["calculated_at"] for r in records if r.get("calculated_at"))
    recent_warnings = [r for r in records if r.get("calculated_at") == latest_batch]

    return [
        {
            "courseName": r["course_title"] or "Unknown Course",
            "courseCode": r["course_code"] or "N/A",
            "matchPercentage": r["score"] or 0
        }
        for r in recent_warnings
    ]

@router.get("/dashboard/kpi")
def get_kpi_data():
    try:
        job_response = supabase.from_("job_skills").select("job_skills").execute()
        course_response = supabase.from_("course_alignment_scores").select("score").execute()
        job_data = job_response.data
        course_data = course_response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching KPI data: {str(e)}")

    scores = [r["score"] for r in course_data if r.get("score") is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    return {
        "averageAlignmentScore": avg_score,
        "totalSubjectsAnalyzed": len(course_data),
        "totalJobPostsAnalyzed": len(job_data),
        "skillsExtracted": len(set(
            s.strip().lower()
            for r in job_data
            for s in r.get("job_skills", "").split(",") if s.strip()
        ))
    }
