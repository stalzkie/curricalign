from __future__ import annotations

import re
import time
import json
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

# --------------------------- New caps & limits ---------------------------
DEFAULT_LIST_LIMIT = 200         # default response size
MAX_LIST_LIMIT = 2000            # hard ceiling for response size
PAGINATION_HARD_CAP = 20000      # stop scanning after this many rows fetched

# --------------------------- Tiny in-memory cache ---------------------------
_CACHE: dict[str, tuple[float, Any]] = {}

def _cache_get(key: str, ttl: float):
    v = _CACHE.get(key)
    if not v:
        return None
    ts, payload = v
    if time.time() - ts > ttl:
        _CACHE.pop(key, None)
        return None
    return payload

def _cache_set(key: str, payload: Any):
    _CACHE[key] = (time.time(), payload)

# --------------------------- Helpers ---------------------------

def _get_sb(request: Request):
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client not available on app state.")
    return sb


def _retry_supabase_sync(call: Callable[[], T], attempts: int = 3, base_delay: float = 0.2) -> T:
    """ Retry wrapper for transient Supabase/HTTP errors. """
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return call()
        except Exception as e:
            transient = (
                (httpx is not None and isinstance(e, (getattr(httpx, "ReadError", Exception), getattr(httpx, "RemoteProtocolError", Exception))))
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


def _fetch_all_rows(
    sb,
    table: str,
    columns: str,
    chunk: int = 1000,
    order_col: str | None = None,
    hard_cap: int | None = PAGINATION_HARD_CAP,
) -> List[Dict[str, Any]]:
    """
    Paginate with optional stable ORDER BY to avoid dup/miss rows across pages.
    Obeys a hard cap to prevent runaway scans under heavy datasets.
    """
    out: List[Dict[str, Any]] = []
    start = 0
    while True:
        end = start + chunk - 1
        if order_col:
            q = sb.from_(table).select(columns).order(order_col, desc=False).range(start, end)
        else:
            q = sb.from_(table).select(columns).range(start, end)
        resp = _retry_supabase_sync(lambda: q.execute())
        rows = resp.data or []
        out.extend(rows)
        if len(rows) < chunk:
            break
        start += chunk
        if hard_cap and len(out) >= hard_cap:
            break
    return out


def get_average_alignment_score_local(sb) -> float:
    """ Calculates the average alignment score by fetching all scores and performing the average calculation in Python. """
    try:
        rows = _fetch_all_rows(sb, "course_alignment_scores_clean", "score", chunk=1000, order_col=None)
    except Exception as e:
        logging.error(f"Error fetching scores for average calculation: {e!r}")
        return 0.0

    scores = [r.get("score") for r in rows if r.get("score") is not None]
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
    - '["Python","SQL"]'   <-- JSON string list
    - None
    """
    if value is None:
        return []

    # True list
    if isinstance(value, list):
        return [str(s).strip().lower() for s in value if str(s).strip()]

    # JSON text list
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip().lower() for x in arr if str(x).strip()]
            except Exception:
                pass
        # comma-delimited fallback
        return [x.strip().lower() for x in s.split(",") if x.strip()]

    # Fallback scalar
    sval = str(value).strip().lower()
    return [sval] if sval else []


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
    "building ",       # only remove when it's a leading verb
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
    if len(s) > 8 and s.endswith("s"):
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
    "and", "or", "of", "the", "to", "in", "for", "with", "on",
    "using", "experience", "knowledge", "background",
    "skills", "skill", "ability",
}


def _fold_aliases_counts(freq: Dict[str, int], aliases: Dict[str, str]) -> Dict[str, int]:
    """ Fold a {skill: count} dict through ALIASES so variants accumulate into a canonical key. """
    if not freq:
        return {}
    out: Dict[str, int] = {}
    for k, v in freq.items():
        canon = aliases.get(k, k)
        out[canon] = out.get(canon, 0) + v
    return out


def _fold_aliases_set(items: List[str] | set[str], aliases: Dict[str, str]) -> set[str]:
    """ Map each normalized course skill through ALIASES so coverage aligns with job variants. """
    result: set[str] = set()
    for k in items:
        result.add(aliases.get(k, k))
    return result


def _build_normalized_counts(rows: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    """ Split + normalize a field and return frequency counts, filtering noise. Works for both job_skills and course_skills. """
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
    """ Split + normalize a field and return a distinct set, filtering noise. """
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


def _is_fuzzy_member(term: str, population: set[str], threshold: int = 88) -> bool:
    """
    Returns True if term fuzzily matches any member of population with ratio >= threshold.
    Fast-fail exact match; then prefilter candidates by first letter and length band.
    """
    if not term or not population:
        return False
    if term in population:
        return True
    t0 = term[0]
    L = len(term)
    # quick prefilter to cut comparisons drastically
    candidates = [p for p in population if p and p[0] == t0 and abs(len(p) - L) <= 3]
    for p in candidates:
        if _fuzzy_ratio(term, p) >= threshold:
            return True
    return False


# --------------------------- Matched (market) skills reader ---------------------------

def _get_matched_course_skills(sb) -> set[str]:
    """
    Fetch a set of normalized, alias-folded skills coming from the market that courses already cover
    (so they should NOT be considered missing). Reads skills_in_market from course_alignment_scores_clean.
    Handles list or comma-separated strings per row.
    """
    try:
        rows = _fetch_all_rows(sb, "course_alignment_scores_clean", "skills_in_market", chunk=1000, order_col=None)
    except Exception:
        rows = []

    matched_set: set[str] = set()
    if rows:
        for r in rows:
            for raw in _split_skills_maybe_list(r.get("skills_in_market")):
                norm = _normalize_skill(raw)
                if not norm:
                    continue
                if norm in STOPWORDS:
                    continue
                if len(norm) < 2:
                    continue
                matched_set.add(norm)

    # Fold aliases so coverage aligns with job variants
    if matched_set:
        matched_set = _fold_aliases_set(matched_set, ALIASES)
    return matched_set


# --------------------------- Endpoints ---------------------------

@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/skills")
def get_in_demand_skills(
    request: Request,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
):
    """
    Return in-demand skills with normalization + fuzzy dedupe.
    IMPORTANT: paginates through ALL job_skills rows (no 1k cap) in stable order by job_skill_id.
    Example: [{"name": "python", "demand": 233}, ...]
    """
    sb = _get_sb(request)
    try:
        # stable ordered pagination by job_skill_id to ensure no dup/miss across pages
        data = _fetch_all_rows(
            sb,
            "job_skills",
            "job_skill_id, job_skills",
            chunk=1000,
            order_col="job_skill_id",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills: {str(e)}")

    raw_freq: Dict[str, int] = {}
    for record in data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            norm = _normalize_skill(skill)  # removes "building ", etc. when leading
            if not norm:
                continue
            raw_freq[norm] = raw_freq.get(norm, 0) + 1

    # Fold aliases BEFORE fuzzy dedupe so "reactjs" and "react js" funnel into "react"
    folded = _fold_aliases_counts(raw_freq, ALIASES)
    cleaned = _dedupe_frequency(folded, threshold=85)

    sorted_skills = sorted(cleaned.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "demand": demand} for name, demand in sorted_skills[:limit]]


@router.get("/top-courses")
def get_top_courses(
    request: Request,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
):
    sb = _get_sb(request)
    try:
        records = _fetch_all_rows(
            sb,
            "course_alignment_scores_clean",
            "course_title, course_code, score, calculated_at",
            chunk=1000,
            order_col=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching top courses: {str(e)}")

    if not records:
        return []

    latest_batch = max((r.get("calculated_at") for r in records if r.get("calculated_at")), default=None)
    if latest_batch is None:
        recent_records = records
    else:
        recent_records = [r for r in records if r.get("calculated_at") == latest_batch]

    recent_records = recent_records[:limit]

    return [
        {
            "courseName": r.get("course_title") or "Unknown Course",
            "courseCode": r.get("course_code") or "N/A",
            "matchPercentage": r.get("score") or 0,
        }
        for r in recent_records
    ]


@router.get("/jobs")
def get_trending_jobs(
    request: Request,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
):
    sb = _get_sb(request)
    try:
        records = _fetch_all_rows(
            sb,
            "trending_jobs",
            "title, trending_score",
            chunk=1000,
            order_col=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trending jobs: {str(e)}")

    out = [
        {"title": r.get("title", ""), "demand": int(r.get("trending_score", 0) or 0)}
        for r in records
        if (r.get("title") or "").strip()
    ]
    return out[:limit]


@router.get("/missing-skills")
def get_missing_skills(
    request: Request,
    min: int = Query(default=None, ge=1, description="Minimum count threshold (defaults to ~1% of job rows, min 2)"),
    latest_only: bool = Query(default=True, description="If true, use evaluator's latest batch only"),
    # keep strict by default, but allow override
    fuzzy_threshold: int = Query(default=95, ge=0, le=100, description="Fuzzy ratio threshold for variant exclusion"),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    mode: str = Query(default="normal", description="Use 'debug' to force lenient filters for validation"),
):
    """
    Prefer evaluator output (skill_gap_counts), fallback to deterministic API-side calc.
    Extra logic:
    - Reads skills_in_market from course_alignment_scores_clean.
    - Uses fuzzy matching to exclude variations present in the matched set.
    - Response shape is unified with /skills: [{name, demand}]
    """
    sb = _get_sb(request)

    # ---- DEBUG MODE OVERRIDES (fast validation in UI) ----
    if mode.lower() == "debug":
        latest_only = False
        fuzzy_threshold = 100  # disable fuzzy exclusion
        if min is None:
            min = 1
        logging.info("[missing-skills] DEBUG mode active → latest_only=False, fuzzy_threshold=100, min=1 (unless provided)")

    # ---- 1) Threshold (use ordered pagination on job_skills by job_skill_id)
    try:
        job_rows_for_threshold = _fetch_all_rows(
            sb,
            "job_skills",
            "job_skill_id",
            chunk=1000,
            order_col="job_skill_id",
        )
        total_job_rows = len(job_rows_for_threshold)
    except Exception:
        total_job_rows = 1
        
    # CALCULATE THRESHOLD: minimum demand count for a skill to be considered a 'gap'.
    # Lower default floor from 5 → 2 to avoid empty results on small datasets.
    threshold = min if isinstance(min, int) else max(2, int(round((total_job_rows or 1) * 0.01)))
    
    # LOGGING: threshold calculation
    logging.info(
        f"[missing-skills] threshold={threshold} (jobs={total_job_rows}, latest_only={latest_only}, fuzzy={fuzzy_threshold})"
    )

    # ---- 2) Matched/covered market skills from course_alignment_scores_clean
    try:
        matched_set = _get_matched_course_skills(sb)
    except Exception:
        matched_set = set()

    # ---- 3) Evaluator output first (preferred)
    try:
        if latest_only:
            # Query for latest batch ID
            latest = _retry_supabase_sync(
                lambda: sb.from_(SKILL_GAP_TABLE)
                .select("batch_id, calculated_at")
                .order("calculated_at", desc=True)
                .limit(1)
                .execute()
            )
            if latest.data:
                latest_batch = latest.data[0]["batch_id"]
                # Fetch data, applying the threshold directly in the DB query
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
            # Fetch data across all batches, applying the threshold directly in the DB query
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

    # ---- Short cache for this endpoint (include inputs in key)
    ck = f"missing:v2:min={threshold}:latest={latest_only}:fth={fuzzy_threshold}"
    cached = _cache_get(ck, ttl=90)
    if cached is not None and resp is None:
        # Use cached fallback only when preferred path failed to fetch fresh resp
        return cached[:limit]
    
    # LOGGING: Record how many rows were fetched from the evaluator's table
    if resp and resp.data:
        logging.info(
            f"[missing-skills] Evaluator data fetched {len(resp.data)} skills (after DB threshold filter)"
        )
        
    if resp and resp.data:
        # Filter out skills that appear among matched skills (exact or fuzzy variants)
        out = []
        for r in resp.data:
            raw_skill = r.get("skill_norm")
            if not raw_skill:
                continue
            norm = _normalize_skill(raw_skill)
            if not norm:
                continue
            # alias to canonical
            norm = ALIASES.get(norm, norm)
            
            # exclude if present exactly or fuzzily among matched skills
            is_covered = (norm in matched_set) or _is_fuzzy_member(norm, matched_set, threshold=fuzzy_threshold)
            if is_covered:
                continue
            
            # UNIFIED SHAPE for frontend compatibility
            out.append({"name": norm, "demand": int(r.get("count", 0) or 0)})

        out = out[:limit]
        _cache_set(ck, out)
        return out

    # ---- 4) Fallback: deterministic API-side calculation (normalize → alias-fold)
    try:
        job_rows = _fetch_all_rows(
            sb,
            "job_skills",
            "job_skill_id, job_skills",
            chunk=1000,
            order_col="job_skill_id",
        )
        course_rows = _fetch_all_rows(
            sb,
            "course_skills",
            "course_skills",
            chunk=1000,
            order_col=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching skills for fallback: {str(e)}")

    job_freq = _build_normalized_counts(job_rows, "job_skills")
    course_set = _build_normalized_set(course_rows, "course_skills")

    # Alias fold both sides
    job_freq = _fold_aliases_counts(job_freq, ALIASES)
    course_set = _fold_aliases_set(course_set, ALIASES)

    # Merge course coverage with matched_set (market skills already covered by courses)
    if matched_set:
        course_set |= matched_set

    missing = []
    filtered_by_threshold_count = 0
    for skill, count in job_freq.items():
        if count < threshold:
            filtered_by_threshold_count += 1
            continue
        # Exclude if covered exactly or fuzzily by course/matched skills
        if (skill in course_set) or _is_fuzzy_member(skill, course_set, threshold=fuzzy_threshold):
            continue
        # UNIFIED SHAPE for frontend compatibility
        missing.append({"name": skill, "demand": int(count)})
        
    # LOGGING (FALLBACK)
    logging.info(
        f"[missing-skills] Fallback filtered {filtered_by_threshold_count} skills by threshold ({threshold}). "
        f"Resulting missing skills: {len(missing)}"
    )

    missing.sort(key=lambda x: x["demand"], reverse=True)
    missing = missing[:limit]
    _cache_set(ck, missing)
    return missing


@router.get("/warnings")
def get_low_scoring_courses(
    request: Request,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
):
    """
    Keep behavior from your new code (latest batch), BUT restore the score <= 50 filter.
    """
    sb = _get_sb(request)
    try:
        records = _fetch_all_rows(
            sb,
            "course_alignment_scores_clean",
            "course_title, course_code, score, calculated_at",
            chunk=1000,
            order_col=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching warnings: {str(e)}")

    if not records:
        return []

    latest_batch = max((r.get("calculated_at") for r in records if r.get("calculated_at")), default=None)
    if latest_batch is None:
        recent = records
    else:
        recent = [r for r in records if r.get("calculated_at") == latest_batch]

    # RESTORE the low-score filter and sort ascending by score
    low = [r for r in recent if (r.get("score") is not None and r.get("score") <= 50)]
    low.sort(key=lambda r: r.get("score", 999999))

    low = low[:limit]

    return [
        {
            "courseName": r.get("course_title") or "Unknown Course",
            "courseCode": r.get("course_code") or "N/A",
            "matchPercentage": r.get("score") or 0,
        }
        for r in low
    ]


def _count_exact(sb, table: str, id_candidates: list[str] | None = None) -> int:
    """
    Robust row count that works across supabase-py versions without HEAD.
    Tries a list of id columns; falls back to '*' selection.
    """
    id_candidates = id_candidates or ["id"]
    for col in id_candidates:
        try:
            r = _retry_supabase_sync(
                lambda: sb.from_(table).select(col, count="exact").range(0, 0).execute()
            )
            c = int(getattr(r, "count", 0) or 0)
            return c
        except Exception:
            continue
    try:
        r = _retry_supabase_sync(
            lambda: sb.from_(table).select("*", count="exact").range(0, 0).execute()
        )
        return int(getattr(r, "count", 0) or 0)
    except Exception:
        return 0


@router.get("/kpi")
def get_kpi_data(request: Request):
    # short cache to collapse dashboard spikes
    ck = "kpi:v1"
    cached = _cache_get(ck, ttl=60)
    if cached is not None:
        return cached

    sb = _get_sb(request)

    # ----- totals (robust, with fallback table for jobs) -----
    # Your jobs table uses job_id (text). Try that first.
    jobs_total = _count_exact(sb, "jobs", id_candidates=["job_id", "id", "uid"])
    if jobs_total == 0:
        # fallback to job_skills if jobs table has perms/schema issues
        jobs_total = _count_exact(sb, "job_skills", id_candidates=["job_skill_id", "id", "job_id"])

    try:
        subjects_total = _count_exact(sb, "course_alignment_scores_clean", id_candidates=["id"])
    except Exception:
        subjects_total = 0

    # ----- average alignment (robust) -----
    avg_score = 0.0
    try:
        # (A) get latest ts
        latest_row_resp = _retry_supabase_sync(
            lambda: sb.from_("course_alignment_scores_clean")
            .select("calculated_at")
            .order("calculated_at", desc=True)
            .limit(1)
            .execute()
        )
        latest_ts = latest_row_resp.data[0].get("calculated_at") if (latest_row_resp and latest_row_resp.data) else None

        # (B) aggregate
        sel = "coalesce(avg(score)::float8, 0) as avg"
        if latest_ts:
            avg_resp = _retry_supabase_sync(
                lambda: sb.from_("course_alignment_scores_clean").select(sel).eq("calculated_at", latest_ts).execute()
            )
        else:
            avg_resp = _retry_supabase_sync(lambda: sb.from_("course_alignment_scores_clean").select(sel).execute())

        if avg_resp and avg_resp.data and len(avg_resp.data) > 0:
            avg_val = avg_resp.data[0].get("avg", 0)
            avg_score = round(float(avg_val), 2)

        if not avg_score:  # covers 0.0 and None
            avg_score = get_average_alignment_score_local(sb)
    except Exception as e:
        logging.warning(f"[kpi] avg(score) failed: {e!r}")
        try:
            avg_score = get_average_alignment_score_local(sb)
        except Exception as e2:
            logging.warning(f"[kpi] local average fallback failed: {e2!r}")
            avg_score = 0.0

    # ----- skills extracted (stable ordered scan) -----
    skills_extracted = 0
    try:
        job_rows = _fetch_all_rows(sb, "job_skills", "job_skill_id, job_skills", chunk=1000, order_col="job_skill_id")
        uniq = set()
        for r in job_rows:
            for s in _split_skills_maybe_list(r.get("job_skills", "")):
                norm = _normalize_skill(s)
                if norm:
                    uniq.add(norm)
        skills_extracted = len(uniq)
    except Exception:
        pass

    result = {
        "averageAlignmentScore": avg_score,
        "totalSubjectsAnalyzed": subjects_total,
        "totalJobPostsAnalyzed": jobs_total,
        "skillsExtracted": skills_extracted,
    }
    _cache_set(ck, result)
    return result


@router.get("/raw-skills-count")
def get_raw_skills(
    request: Request,
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
):
    """
    Returns a raw, non-normalized count of skills directly from job_skills, over ALL rows.
    Example: [{"name": "Python", "count": 233}, {"name": "JavaScript", "count": 150}]
    """
    sb = _get_sb(request)
    try:
        data = _fetch_all_rows(
            sb,
            "job_skills",
            "job_skill_id, job_skills",
            chunk=1000,
            order_col="job_skill_id",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching raw skills: {str(e)}")

    raw_freq: Dict[str, int] = {}
    for record in data:
        for skill in _split_skills_maybe_list(record.get("job_skills", "")):
            raw_freq[skill] = raw_freq.get(skill, 0) + 1

    sorted_skills = sorted(raw_freq.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "count": int(count)} for name, count in sorted_skills[:limit]]
