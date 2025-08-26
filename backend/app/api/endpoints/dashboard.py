from __future__ import annotations

import time
from typing import Dict, List, Any, Callable, TypeVar
from fastapi import APIRouter, HTTPException, Request
import logging

# trying to use httpx (for handling web requests) but it's optional
try:
    import httpx
except Exception:  # if httpx is not installed, ignore it
    httpx = None 

# httpcore is another library for handling http connections
try:
    from httpcore import RemoteProtocolError 
except Exception:
    # if httpcore is not available, just create a fake error class
    class RemoteProtocolError(Exception):
        pass

# FastAPI router so we can define endpoints (like /skills, /jobs)
router = APIRouter()
T = TypeVar("T")  # generic type variable


# --------------------------- Helpers ---------------------------

# get supabase client (like a database connection) from the app state
def _get_sb(request: Request):
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client not available on app state.")
    return sb


# retry logic for calling supabase in case of random internet errors
def _retry_supabase_sync(call: Callable[[], T], attempts: int = 3, base_delay: float = 0.2) -> T:
    """
    Try calling supabase up to 'attempts' times.
    Wait a little longer after each failed try (0.2, 0.4, 0.8... seconds).
    """
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return call()
        except Exception as e:
            # only retry if the error looks like a temporary connection problem
            transient = (
                (httpx is not None and isinstance(e, (httpx.ReadError, httpx.RemoteProtocolError)))
                or isinstance(e, RemoteProtocolError)
                or "StreamClosedError" in repr(e)
                or "Server disconnected" in repr(e)
            )
            if not transient or i == attempts:
                # if it's not a connection error OR we used all tries, raise error
                raise
            delay = base_delay * (2 ** (i - 1))  # wait time grows each attempt
            logging.warning(f"[dashboard] transient supabase error on attempt {i}/{attempts}: {e!r}; retrying in {delay:.1f}s")
            time.sleep(delay)
            last_exc = e
    assert last_exc is not None
    raise last_exc


# function to clean up skills data (since it can be string, list, or empty)
def _split_skills_maybe_list(value: Any) -> List[str]:
    """
    Converts the skills data into a list of lowercase strings.
    Handles cases like:
    - ['Python', 'SQL']
    - "Python, SQL"
    - None
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(s).strip().lower() for s in value if str(s).strip()]
    if isinstance(value, str):
        return [s.strip().lower() for s in value.split(",") if s.strip()]
    return [str(value).strip().lower()] if str(value).strip() else []


# --------------------------- Endpoints ---------------------------

# API route to get the most in-demand skills
@router.get("/skills")
def get_in_demand_skills(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        data = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    # count how many times each skill appears
    frequency: Dict[str, int] = {}
    for record in data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            frequency[skill] = frequency.get(skill, 0) + 1

    # sort skills by frequency (most popular first)
    sorted_skills = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "demand": demand} for name, demand in sorted_skills]


# API route to get top scoring courses
@router.get("/top-courses")
def get_top_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")   # ✅ switched to clean table
            .select("course_title, course_code, score, calculated_at")
            .order("score", desc=True)
            .execute()
        )
        records = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching top courses: {str(e)}")

    if not records:
        return []

    # only use the most recent results
    latest_batch = max((r.get("calculated_at") for r in records if r.get("calculated_at")), default=None)
    if latest_batch is None:
        recent_records = records
    else:
        recent_records = [r for r in records if r.get("calculated_at") == latest_batch]

    return [
        {
            "courseName": r.get("course_title") or "Unknown Course",
            "courseCode": r.get("course_code") or "N/A",
            "matchPercentage": r.get("score") or 0,
        }
        for r in recent_records
    ]


# API route to get trending jobs
@router.get("/jobs")
def get_trending_jobs(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("trending_jobs")
            .select("title, trending_score")
            .order("trending_score", desc=True)
            .execute()
        )
        records = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trending jobs: {str(e)}")

    # return job titles with their demand score
    return [
        {"title": r.get("title", ""), "demand": r.get("trending_score", 0)}
        for r in records
        if (r.get("title") or "").strip()
    ]


# API route to get missing skills (skills jobs want but courses don't teach)
@router.get("/missing-skills")
def get_missing_skills(request: Request):
    sb = _get_sb(request)
    try:
        job_resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        course_resp = _retry_supabase_sync(lambda: sb.from_("course_skills").select("course_skills").execute())
        job_data = job_resp.data or []
        course_data = course_resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    job_skills_set = set()
    for record in job_data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            job_skills_set.add(skill)

    course_skills_set = set()
    for record in course_data:
        for skill in _split_skills_maybe_list(record.get("course_skills", [])):
            course_skills_set.add(skill)

    # missing = skills that appear in jobs but not in courses
    missing = sorted(list(job_skills_set - course_skills_set))
    return missing


# API route to get low scoring courses (courses that don’t align with jobs well)
@router.get("/warnings")
def get_low_scoring_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")   # ✅ switched to clean table
            .select("course_title, course_code, score, calculated_at")
            .lte("score", 50)  # only scores <= 50
            .order("score", desc=False)
            .execute()
        )
        records = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching warnings: {str(e)}")

    if not records:
        return []

    latest_batch = max((r.get("calculated_at") for r in records if r.get("calculated_at")), default=None)
    if latest_batch is None:
        recent = records
    else:
        recent = [r for r in records if r.get("calculated_at") == latest_batch]

    return [
        {
            "courseName": r.get("course_title") or "Unknown Course",
            "courseCode": r.get("course_code") or "N/A",
            "matchPercentage": r.get("score") or 0,
        }
        for r in recent
    ]


# API route to get KPI data (summary numbers)
@router.get("/kpi")
def get_kpi_data(request: Request):
    sb = _get_sb(request)
    try:
        job_resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        course_resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")   # ✅ switched to clean table
            .select("score")
            .execute()
        )
        job_data = job_resp.data or []
        course_data = course_resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching KPI data: {str(e)}")

    # average score across all courses
    scores = [r.get("score") for r in course_data if r.get("score") is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    # count unique job skills
    unique_skills = set()
    for r in job_data:
        for s in _split_skills_maybe_list(r.get("job_skills", "")):
            unique_skills.add(s)

    return {
        "averageAlignmentScore": avg_score,
        "totalSubjectsAnalyzed": len(course_data),
        "totalJobPostsAnalyzed": len(job_data),
        "skillsExtracted": len(unique_skills),
    }
