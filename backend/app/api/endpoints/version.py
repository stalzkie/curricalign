# backend/app/api/endpoints/version.py
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple, Dict

from fastapi import APIRouter, Header, Response, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["dashboard-version"])

# Tables that affect the dashboard's data freshness
DASHBOARD_TABLES: Tuple[str, ...] = (
    "jobs",
    "job_skills",
    "courses",
    "course_skills",
    "course_alignment_scores_clean",
    "trending_jobs",
    "skill_gap_counts",
)

# Preferred timestamp columns per table (checked in order)
PREFERRED_TS_COLS: Dict[str, Tuple[str, ...]] = {
    "jobs": ("updated_at", "created_at"),
    "job_skills": ("updated_at", "date_extracted_jobs", "created_at", "calculated_at"),
    "courses": ("updated_at", "created_at"),
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
    """Parse ISO-ish timestamps into aware UTC datetimes; None if invalid."""
    if not ts:
        return None
    try:
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

def _max_ts_from_table_versions(sb, tables: Iterable[str]) -> Optional[datetime]:
    """
    Preferred: read the newest updated_at from public.table_versions for the given tables.
    Requires a 'touch_table_version' trigger on those tables.
    Uses the SAME Supabase client as the rest of the API (RLS-consistent).
    """
    try:
        resp = (
            sb.table("table_versions")
            .select("table_name, updated_at")
            .in_("table_name", list(tables))
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if rows and rows[0].get("updated_at"):
            return _to_dt(rows[0]["updated_at"])
        return None
    except Exception:
        return None  # table_versions might not exist; fall back to scans

def _max_ts_for_table(sb, table: str) -> Optional[datetime]:
    """
    Fallback: probe likely timestamp columns and return the newest non-NULL value.
    Uses NULL-safe ordering so NULLs never block freshness.
    """
    cols = PREFERRED_TS_COLS.get(table, DEFAULT_TS_ORDER)
    for col in cols:
        try:
            q = (
                sb.table(table)
                .select(col)
                .order(col, desc=True, nullsfirst=False)  # NULLS LAST
                .limit(1)
                .execute()
            )
        except Exception:
            # Column may not exist on this table/view → try next candidate
            continue

        rows = getattr(q, "data", None) or []
        if not rows:
            continue

        dt = _to_dt(rows[0].get(col))
        if dt:
            return dt
    return None

def _max_ts_across_tables_via_scan(sb, tables: Iterable[str]) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for t in tables:
        dt = _max_ts_for_table(sb, t)
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest

@router.get("/version")
def get_dashboard_version(
    request: Request,
    response: Response,
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
):
    """
    Returns a single canonical timestamp for the dashboard's data freshness,
    computed with the SAME Supabase client as the data endpoints (RLS-consistent).

    200 OK:
      { "lastChanged": "2025-08-26T13:40:11.123Z" }

    304 Not Modified:
      (empty body) when If-None-Match matches current ETag

    NOTE: Include this router with prefix `/api/dashboard` so the frontend hits /api/dashboard/version
          e.g., app.include_router(version.router, prefix="/api/dashboard")
    """
    # Use the same client the rest of your API uses
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client not available on app state.")

    try:
        # 1) Preferred: table_versions (fast & exact)
        latest = _max_ts_from_table_versions(sb, DASHBOARD_TABLES)

        # 2) Fallback: scan source tables with NULL-safe ordering
        if latest is None:
            latest = _max_ts_across_tables_via_scan(sb, DASHBOARD_TABLES)

        # 3) If still nothing, stabilize at epoch so caches can initialize
        if latest is None:
            latest = datetime(1970, 1, 1, tzinfo=timezone.utc)

        last_changed_iso = _fmt_iso(latest)
        etag = _sha_etag(last_changed_iso)

        # Conditional GET (If-None-Match)
        if if_none_match and if_none_match.strip('"') == etag:
            r = Response(status_code=304)
            r.headers["ETag"] = f'"{etag}"'
            r.headers["Cache-Control"] = "no-store"
            return r

        payload = {"lastChanged": last_changed_iso}
        r = JSONResponse(content=payload)
        r.headers["ETag"] = f'"{etag}"'
        r.headers["Cache-Control"] = "no-store"
        return r

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Version endpoint failed: {exc}")
