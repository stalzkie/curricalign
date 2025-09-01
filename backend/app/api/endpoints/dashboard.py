from __future__ import annotations

import re
import time
import logging
from typing import Dict, List, Any, Callable, TypeVar

from fastapi import APIRouter, HTTPException, Request, Query

# optional http clients
try:
    import httpx
except Exception:
    httpx = None

try:
    from httpcore import RemoteProtocolError
except Exception:
    class RemoteProtocolError(Exception):
        pass

# fuzzy matching (optional, with graceful fallback)
try:
    from rapidfuzz import fuzz as _rf_fuzz
    def _fuzzy_ratio(a: str, b: str) -> int:
        # rapidfuzz returns 0..100
        return int(_rf_fuzz.ratio(a, b))
except Exception:
    def _fuzzy_ratio(a: str, b: str) -> int:
        # fallback: exact match only
        return 100 if a == b else 0

router = APIRouter()
T = TypeVar("T")

SKILL_GAP_TABLE = "skill_gap_counts"  # ← evaluator writes unmatched skills here


# --------------------------- Helpers ---------------------------

def _get_sb(request: Request):
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client not available on app state.")
    return sb


def _retry_supabase_sync(call: Callable[[], T], attempts: int = 3, base_delay: float = 0.2) -> T:
    """
    Retry wrapper for transient Supabase/HTTP errors.
    """
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return call()
        except Exception as e:
            transient = (
                (httpx is not None and isinstance(e, (httpx.ReadError, httpx.RemoteProtocolError)))
                or isinstance(e, RemoteProtocolError)
                or "StreamClosedError" in repr(e)
                or "Server disconnected" in repr(e)
            )
            if not transient or i == attempts:
                raise
            delay = base_delay * (2 ** (i - 1))
            logging.warning(
                f"[dashboard] transient supabase error on attempt {i}/{attempts}: {e!r}; "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)
            last_exc = e
    assert last_exc is not None
    raise last_exc


def get_average_alignment_score_local(sb) -> float:
    """
    Calculates the average alignment score by fetching all scores
    and performing the average calculation in Python.
    """
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")
            .select("score")
            .execute()
        )
        data = resp.data or []
    except Exception as e:
        logging.error(f"Error fetching scores for average calculation: {e!r}")
        return 0.0

    scores = [r.get("score") for r in data if r.get("score") is not None]
    if not scores:
        return 0.0

    avg_score = sum(scores) / len(scores)
    return round(avg_score, 2)


def _split_skills_maybe_list(value: Any) -> List[str]:
    """
    Converts the skills data into a list of lowercase strings.
    Handles:
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


# ---------- Normalization & dedupe for skills ----------

# Leading phrases/verbs that often precede real skills.
# NOTE the trailing space for verbs to ensure we only strip at the start.
_PREFIXES = (
    "using ",
    "with ",
    "knowledge of ",
    "experience in ",
    "proficient in ",
    "familiar with ",
    "building ",      # only remove when it's a leading verb
    "developing ",
    "creating ",
    "designing ",
    "implementing ",
    "maintaining ",
    "administering ",
)

# keep alphanumerics, +, #, and whitespace; replace other punct with space
_PUNCT_RE = re.compile(r"[^a-z0-9\+\#\s]+")
_WS_RE = re.compile(r"\s+")

def _normalize_skill(raw: str) -> str:
    """
    Canonical normalization for grouping:
      - lowercase, trim
      - strip common leading phrases/verbs ("using ", "building ", ...)
      - remove most punctuation (keep + and #), collapse whitespace
      - very light plural trim (trailing 's' for longer tokens)
    """
    s = (raw or "").strip().lower()
    for p in _PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    # light plural normalization (avoid over-aggressive trimming)
    if len(s) > 6 and s.endswith("s"):
        s = s[:-1]
    return s

def _dedupe_frequency(freq: Dict[str, int], threshold: int = 85) -> Dict[str, int]:
    """
    Fuzzy-dedupe a frequency dict {skill: count}:
      - iterate by highest count first
      - merge into an existing representative if fuzzy ratio >= threshold
    """
    if not freq:
        return {}
    items = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
    merged: Dict[str, int] = {}

    for skill, count in items:
        norm = _normalize_skill(skill)
        if not norm:
            continue
        representative = None
        for rep in merged.keys():
            if _fuzzy_ratio(norm, rep) >= threshold:
                representative = rep
                break
        if representative is None:
            merged[norm] = count
        else:
            merged[representative] += count
    return merged


# --------------------------- Simple alias support (deterministic) ---------------------------

# Map normalized *variants* -> *canonical* names. Start small; grow as needed.
ALIASES: Dict[str, str] = {
    "js": "javascript",
    "react js": "react",
    "reactjs": "react",
    "node js": "node",
    "nodejs": "node",
    "python3": "python",
    "sql query": "sql",
    "sql querie": "sql",
}

# Generic noise tokens to ignore
STOPWORDS = {
    "and", "or", "of", "the", "to", "in", "for", "with", "on", "using",
    "experience", "knowledge", "background", "skills", "skill", "ability",
}

def _fold_aliases_counts(freq: Dict[str, int], aliases: Dict[str, str]) -> Dict[str, int]:
    """
    Fold a {skill: count} dict through ALIASES so variants accumulate into a canonical key.
    """
    if not freq:
        return {}
    out: Dict[str, int] = {}
    for k, v in freq.items():
        canon = aliases.get(k, k)
        out[canon] = out.get(canon, 0) + v
    return out

def _fold_aliases_set(items: List[str] | set[str], aliases: Dict[str, str]) -> set[str]:
    """
    Map each normalized course skill through ALIASES so coverage aligns with job variants.
    """
    result: set[str] = set()
    for k in items:
        result.add(aliases.get(k, k))
    return result

def _build_normalized_counts(rows: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    """
    Split + normalize a field and return frequency counts, filtering noise.
    Works for both `job_skills` and `course_skills`.
    """
    freq: Dict[str, int] = {}
    for r in rows:
        for raw in _split_skills_maybe_list(r.get(field, "")):
            norm = _normalize_skill(raw)
            if not norm:
                continue
            if norm in STOPWORDS:
                continue
            if len(norm) < 2:
                continue
            freq[norm] = freq.get(norm, 0) + 1
    return freq

def _build_normalized_set(rows: List[Dict[str, Any]], field: str) -> set[str]:
    """
    Split + normalize a field and return a distinct set, filtering noise.
    """
    s: set[str] = set()
    for r in rows:
        for raw in _split_skills_maybe_list(r.get(field, "")):
            norm = _normalize_skill(raw)
            if not norm:
                continue
            if norm in STOPWORDS:
                continue
            if len(norm) < 2:
                continue
            s.add(norm)
    return s


# --------------------------- Endpoints ---------------------------

@router.get("/skills")
def get_in_demand_skills(request: Request):
    """
    Return in-demand skills with normalization + fuzzy dedupe.
    Example: [{"name": "python", "demand": 233}, ...]
    """
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        data = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    raw_freq: Dict[str, int] = {}
    for record in data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            norm = _normalize_skill(skill)  # removes "building ", etc. when leading
            if not norm:
                continue
            raw_freq[norm] = raw_freq.get(norm, 0) + 1

    cleaned = _dedupe_frequency(raw_freq, threshold=85)
    sorted_skills = sorted(cleaned.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "demand": demand} for name, demand in sorted_skills]


@router.get("/top-courses")
def get_top_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")
            .select("course_title, course_code, score, calculated_at")
            .order("score", desc=True)
            .execute()
        )
        records = resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching top courses: {str(e)}")

    if not records:
        return []

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
def get_missing_skills(
    request: Request,
    min: int = Query(default=None, ge=1, description="Minimum count threshold (defaults to ~1% of job rows, min 5)"),
    latest_only: bool = Query(default=True, description="If true, use evaluator's latest batch only"),
):
    """
    Prefer evaluator output (skill_gap_counts), fallback to deterministic API-side calc.

    Flow:
      1) Determine default threshold: ~1% of job rows (min 5), unless ?min= provided.
      2) Try to read evaluator’s aggregated unmatched skills from `skill_gap_counts`.
         - If latest_only=True, pick the newest batch_id by calculated_at.
         - Return rows with count >= threshold, ordered by count desc.
      3) If no rows, fallback:
         - Normalize both sides deterministically, fold small alias map,
           compute exact set diff with counts, apply threshold.
    """
    sb = _get_sb(request)

    # ---- 1) Threshold
    try:
        job_count_resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("id").execute())
        total_job_rows = len(job_count_resp.data or [])
    except Exception:
        total_job_rows = 1
    threshold = min if isinstance(min, int) else max(5, int(round((total_job_rows or 1) * 0.01)))

    # ---- 2) Evaluator output first (preferred)
    try:
        if latest_only:
            latest = _retry_supabase_sync(
                lambda: sb.from_(SKILL_GAP_TABLE)
                .select("batch_id, calculated_at")
                .order("calculated_at", desc=True)
                .limit(1)
                .execute()
            )
            if latest.data:
                latest_batch = latest.data[0]["batch_id"]
                resp = _retry_supabase_sync(
                    lambda: sb.from_(SKILL_GAP_TABLE)
                    .select("skill_norm, count")
                    .eq("batch_id", latest_batch)
                    .gte("count", threshold)
                    .order("count", desc=True)
                    .execute()
                )
            else:
                resp = None
        else:
            resp = _retry_supabase_sync(
                lambda: sb.from_(SKILL_GAP_TABLE)
                .select("skill_norm, count, calculated_at")
                .gte("count", threshold)
                .order("calculated_at", desc=True)
                .order("count", desc=True)
                .execute()
            )
    except Exception as e:
        resp = None
        logging.warning(f"[dashboard] reading {SKILL_GAP_TABLE} failed, will fallback: {e!r}")

    if resp and resp.data:
        out = [{"skill": r["skill_norm"], "count": int(r["count"])} for r in resp.data if r.get("skill_norm")]
        return out

    # ---- 3) Fallback: deterministic API-side calculation (normalize → alias-fold → exact diff)
    try:
        job_resp = _retry_supabase_sync(lambda: sb.from_("job_skills").select("job_skills").execute())
        course_resp = _retry_supabase_sync(lambda: sb.from_("course_skills").select("course_skills").execute())
        job_rows = job_resp.data or []
        course_rows = course_resp.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills for fallback: {str(e)}")

    job_freq = _build_normalized_counts(job_rows, "job_skills")
    course_set = _build_normalized_set(course_rows, "course_skills")
    job_freq = _fold_aliases_counts(job_freq, ALIASES)
    course_set = _fold_aliases_set(course_set, ALIASES)

    missing = [
        {"skill": skill, "count": count}
        for skill, count in job_freq.items()
        if (skill not in course_set) and (count >= threshold)
    ]
    missing.sort(key=lambda x: x["count"], reverse=True)
    return missing


@router.get("/warnings")
def get_low_scoring_courses(request: Request):
    sb = _get_sb(request)
    try:
        resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")
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

    def _count_exact(table: str) -> int:
        # Uses PostgREST Content-Range; no 1000 cap
        r = _retry_supabase_sync(
            lambda: sb.from_(table).select("*", count="exact", head=True).execute()
        )
        return int(getattr(r, "count", None) or 0)

    # ----- totals (robust, with fallback table for jobs) -----
    try:
        jobs_total = _count_exact("jobs")
    except Exception:
        # fallback to job_skills if jobs table has perms/schema issues
        try:
            jobs_total = _count_exact("job_skills")
        except Exception:
            jobs_total = 0

    try:
        subjects_total = _count_exact("course_alignment_scores_clean")
    except Exception:
        subjects_total = 0

    # ----- average alignment (robust) -----
    avg_score = 0.0
    try:
        # (A) get latest ts (like /top-courses)
        latest_ts = None
        latest_row_resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")
            .select("calculated_at")
            .order("calculated_at", desc=True)
            .limit(1)
            .execute()
        )
        if latest_row_resp and latest_row_resp.data:
            latest_ts = latest_row_resp.data[0].get("calculated_at")

        # (B) aggregate with COALESCE + cast
        sel = "coalesce(avg(score)::float8, 0) as avg"
        if latest_ts:
            avg_resp = _retry_supabase_sync(
                lambda: sb.from_("course_alignment_scores_clean")
                .select(sel)
                .eq("calculated_at", latest_ts)
                .execute()
            )
        else:
            avg_resp = _retry_supabase_sync(
                lambda: sb.from_("course_alignment_scores_clean")
                .select(sel)
                .execute()
            )

        if avg_resp and avg_resp.data and len(avg_resp.data) > 0:
            avg_val = avg_resp.data[0].get("avg", 0)
            avg_score = round(float(avg_val), 2)

        # (C) Fallback: compute locally in Python if aggregate is zero/empty
        if not avg_score:  # covers 0.0 and None
            avg_score = get_average_alignment_score_local(sb)

    except Exception as e:
        logging.warning(f"[kpi] avg(score) failed: {e!r}")
        # Final safety: try local fallback if aggregate path crashed
        try:
            avg_score = get_average_alignment_score_local(sb)
        except Exception as e2:
            logging.warning(f"[kpi] local average fallback failed: {e2!r}")
            avg_score = 0.0

    # ----- skills extracted (sampled; switch to RPC if you need exact) -----
    skills_extracted = 0
    try:
        job_sample = _retry_supabase_sync(
            lambda: sb.from_("job_skills").select("job_skills").limit(1000).execute()
        ).data or []
        uniq = set()
        for r in job_sample:
            for s in _split_skills_maybe_list(r.get("job_skills", "")):
                uniq.add(_normalize_skill(s))
        skills_extracted = len(uniq)
    except Exception:
        pass

    return {
        "averageAlignmentScore": avg_score,
        "totalSubjectsAnalyzed": subjects_total,
        "totalJobPostsAnalyzed": jobs_total,
        "skillsExtracted": skills_extracted,
    }


# ---------- Optional debug endpoint for local average ----------

@router.get("/kpi/local-average")
def get_kpi_local_average(request: Request):
    sb = _get_sb(request)
    avg = get_average_alignment_score_local(sb)
    return {"averageAlignmentScore": avg}
