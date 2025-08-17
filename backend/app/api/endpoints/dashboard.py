from __future__ import annotations

import time
from typing import Dict, List, Any, Callable, TypeVar
from fastapi import APIRouter, HTTPException, Request
import logging

# httpx/httpcore transient error types (names differ between versions)
try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

try:
    from httpcore import RemoteProtocolError  # type: ignore
except Exception:
    class RemoteProtocolError(Exception):  # fallback
        pass

router = APIRouter()
T = TypeVar("T")


def _get_sb(request: Request):
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client not available on app state.")
    return sb


def _retry_supabase_sync(call: Callable[[], T], attempts: int = 3, base_delay: float = 0.2) -> T:
    """
    Very small retry/backoff for transient HTTP/2/connection hiccups between FastAPI and Supabase.
    Works with the sync supabase-py v1 client.
    """
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return call()
        except Exception as e:
            # Only retry on likely transient transport/protocol errors
            transient = (
                (httpx is not None and isinstance(e, (httpx.ReadError, httpx.RemoteProtocolError)))
                or isinstance(e, RemoteProtocolError)
                or "StreamClosedError" in repr(e)
                or "Server disconnected" in repr(e)
            )
            if not transient or i == attempts:
                # non-transient OR out of attempts -> raise
                raise
            delay = base_delay * (2 ** (i - 1))  # 0.2, 0.4, 0.8
            logging.warning(f"[dashboard] transient supabase error on attempt {i}/{attempts}: {e!r}; retrying in {delay:.1f}s")
            time.sleep(delay)
            last_exc = e
    assert last_exc is not None
    raise last_exc


def _split_skills_maybe_list(value: Any) -> List[str]:
    """
    Normalizes a skills column that can be either:
      - list[str] (preferred)
      - comma-separated string "python, sql"
      - None
    Returns a list of normalized lowercase strings with whitespace trimmed.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(s).strip().lower() for s in value if str(s).strip()]
    if isinstance(value, str):
        return [s.strip().lower() for s in value.split(",") if s.strip()]
    # unknown type: best effort
    return [str(value).strip().lower()] if str(value).strip() else []


@router.get("/skills")
def get_in_demand_skills(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        data = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    frequency: Dict[str, int] = {}
    for record in data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            frequency[skill] = frequency.get(skill, 0) + 1

    sorted_skills = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "demand": demand} for name, demand in sorted_skills]


@router.get("/top-courses")
def get_top_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores")
            .select("course_title, course_code, score, calculated_at")
            .order("score", desc=True)
            .execute()
        )
        records = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching top courses: {str(e)}")

    if not records:
        return []

    # Use the most recent calculation batch
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

    return [
        {"title": r.get("title", ""), "demand": r.get("trending_score", 0)}
        for r in records
        if (r.get("title") or "").strip()
    ]


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

    missing = sorted(list(job_skills_set - course_skills_set))
    # Return as a list of strings (your frontend already normalizes)
    return missing


@router.get("/warnings")
def get_low_scoring_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores")
            .select("course_title, course_code, score, calculated_at")
            .lte("score", 50)
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


@router.get("/kpi")
def get_kpi_data(request: Request):
    sb = _get_sb(request)
    try:
        job_resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        course_resp = _retry_supabase_sync(lambda: sb.from_("course_alignment_scores").select("score").execute())
        job_data = job_resp.data or []
        course_data = course_resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching KPI data: {str(e)}")

    scores = [r.get("score") for r in course_data if r.get("score") is not None]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    # Count unique job skills robustly
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
