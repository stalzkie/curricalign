# backend/app/api/endpoints/version.py
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple, Dict

from fastapi import APIRouter, Header, Response, HTTPException
from fastapi.responses import JSONResponse

# Initialized Supabase client (v2)
from ...core.supabase_client import supabase

router = APIRouter(tags=["dashboard-version"])

# Tables that affect the dashboard's data freshness
DASHBOARD_TABLES: Tuple[str, ...] = (
    "jobs",
    "job_skills",
    "course_skills",
    "course_alignment_scores_clean",
    "trending_jobs",
    "skill_gap_counts",  # ← NEW: evaluator writes unmatched skills here
)

# Preferred timestamp columns per table (checked in order).
# If a column doesn't exist or is null-only, we fall back to the next.
PREFERRED_TS_COLS: Dict[str, Tuple[str, ...]] = {
    "jobs": ("updated_at", "created_at"),
    "job_skills": ("updated_at", "date_extracted_jobs", "created_at", "calculated_at"),
    "course_skills": ("updated_at", "date_extracted_course", "created_at"),
    "course_alignment_scores_clean": ("calculated_at", "updated_at", "created_at"),
    "trending_jobs": ("updated_at", "created_at", "calculated_at"),
    "skill_gap_counts": ("calculated_at", "updated_at", "created_at"),
}

# Generic fallback order if a table isn't in PREFERRED_TS_COLS
DEFAULT_TS_ORDER: Tuple[str, ...] = (
    "updated_at",
    "created_at",
    "calculated_at",
    "inserted_at",
    "timestamp",
    "ts",
)


def _to_dt(ts: Optional[str]) -> Optional[datetime]:
    """
    Parse common timestamp formats from Supabase/PostgREST into aware UTC datetimes.
    Returns None if input is falsy or parsing fails.
    """
    if not ts:
        return None
    try:
        # Support both Z and +/- offsets
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _fmt_iso(dt: datetime) -> str:
    """Uniform ISO8601 in UTC with 'Z' suffix."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_etag(text: str) -> str:
    """Strong ETag from a small payload."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _max_ts_for_table(table: str) -> Optional[datetime]:
    """
    Returns the most recent timestamp for a single table by probing a set of likely columns.
    We try each candidate column (desc order, limit 1) and return the first non-null value.
    """
    cols = PREFERRED_TS_COLS.get(table, DEFAULT_TS_ORDER)

    for col in cols:
        try:
            # Ask only for the column we care about; order desc so the newest non-null should surface.
            q = (
                supabase.table(table)
                .select(col)
                .order(col, desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            # Column may not exist; try next candidate
            continue

        rows = getattr(q, "data", None) or []
        if not rows:
            # Table may be empty; try next candidate column
            continue

        # Take the first row's value for this column (ordered desc)
        value = rows[0].get(col)
        dt = _to_dt(value)
        if dt:
            return dt

        # If top row is null for this column, try next candidate
        # (Some tables have mixed nulls / legacy rows.)
    return None


def _max_ts_across_tables(tables: Iterable[str]) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for t in tables:
        dt = _max_ts_for_table(t)
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest


@router.get("/version")
def get_dashboard_version(
    response: Response,
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
):
    """
    Returns a single canonical timestamp for the dashboard's data freshness.

    Responses:
      200 OK:
        { "lastChanged": "2025-08-26T13:40:11.123Z" }

      304 Not Modified:
        (empty body) when If-None-Match matches current ETag
    """
    try:
        latest = _max_ts_across_tables(DASHBOARD_TABLES)

        # If no rows exist anywhere yet, stabilize at epoch
        if latest is None:
            latest = datetime(1970, 1, 1, tzinfo=timezone.utc)

        last_changed_iso = _fmt_iso(latest)
        etag = _sha_etag(last_changed_iso)

        # Conditional GET
        if if_none_match and if_none_match.strip('"') == etag:
            # Not changed since client’s last version
            resp = Response(status_code=304)
            resp.headers["ETag"] = f'"{etag}"'
            resp.headers["Cache-Control"] = "no-store"
            return resp

        # Normal 200 response
        payload = {"lastChanged": last_changed_iso}
        resp = JSONResponse(content=payload)
        resp.headers["ETag"] = f'"{etag}"'
        resp.headers["Cache-Control"] = "no-store"
        return resp

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Version endpoint failed: {exc}")
