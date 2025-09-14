# apps/backend/main.py

import os
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from supabase import create_client, Client

# Routers
from .api.endpoints import dashboard, pipeline, orchestrator, report_files, version
from .api.endpoints import scan_pdf as scan_pdf_endpoint  # <-- NEW

# -------------------------------------------------------------------
# Environment / logging
# -------------------------------------------------------------------
os.environ.setdefault("HTTPX_DISABLE_HTTP2", "1")  # Cloudflare/HTTP2 quirks
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [main] %(message)s",
)


def _get_service_key() -> tuple[str, str]:
    """
    Load Supabase URL and a **service** key (not anon).
    Supports several common env names to avoid misconfig.
    """
    url = (
        os.getenv("SUPABASE_URL")
        or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        or ""
    ).strip()

    # Prefer explicit service role envs; fall back to generic SUPABASE_KEY
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")   # common
        or os.getenv("SUPABASE_SERVICE_ROLE")    # alias
        or os.getenv("SUPABASE_SERVICE_KEY")     # alias
        or os.getenv("SUPABASE_SERVICE_API_KEY") # alias
        or os.getenv("SUPABASE_KEY")             # last resort; must be service-level, not anon
        or ""
    ).strip()

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Ensure SUPABASE_URL and a service key "
            "(e.g., SUPABASE_SERVICE_ROLE_KEY) are set in the environment."
        )
    return url, key


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Application startup…")
    url, key = _get_service_key()

    sb: Client = create_client(url, key)
    app.state.supabase = sb
    logging.info("Supabase service client attached to app.state.supabase")

    # Quick probe: tiny exact count to confirm RLS/keys are correct.
    # We wrap in try/except so startup never crashes on a read error.
    try:
        resp = (
            sb.from_("course_alignment_scores_clean")
            .select("course_alignment_scores_clean_id", count="exact")  # ✅ fixed column name
            .range(0, 0)
            .execute()
        )
        cnt = int(getattr(resp, "count", 0) or 0)
        logging.info("[probe] course_alignment_scores_clean count=%s", cnt)
    except Exception as e:
        logging.warning("[probe] count failed: %r", e)

    yield
    logging.info("Application shutdown.")


app = FastAPI(
    title="CurricAlign API",
    description="API for curriculum-job market alignment pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
from fastapi.middleware.cors import CORSMiddleware

allowed_origins = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost",
}
extra_origin = os.getenv("FRONTEND_ORIGIN", "").strip()
if extra_origin:
    allowed_origins.add(extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),              # explicit origins
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",  # safety net
    allow_credentials=True,
    allow_methods=["*"],      # includes OPTIONS
    allow_headers=["*"],      # allow Content-Type, etc.
    expose_headers=["*"],
    max_age=86400,            # cache preflight
)

# -------------------------------------------------------------------
# Static files (PDF reports, etc.)
# -------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent               # apps/backend/app
STATIC_DIR = (APP_DIR / "static").resolve()             # apps/backend/app/static
REPORTS_DIR = (STATIC_DIR / "reports").resolve()        # apps/backend/app/static/reports
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# -------------------------------------------------------------------
# Health + Root
# -------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """
    Liveness/readiness probe. Also verifies DB read briefly.
    """
    sb: Client | None = getattr(app.state, "supabase", None)
    if sb is None:
        raise HTTPException(status_code=500, detail="Supabase client missing")

    try:
        resp = sb.from_("jobs").select("job_id", count="exact").range(0, 0).execute()
        jobs = int(getattr(resp, "count", 0) or 0)
    except Exception as e:
        logging.warning("[healthz] jobs count failed: %r", e)
        jobs = -1

    return {"ok": True, "jobsCount": jobs}

@app.get("/")
def read_root():
    return {"message": "Welcome to the CurricAlign API"}

# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------
app.include_router(dashboard.router,    prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(version.router,      prefix="/api/dashboard", tags=["Dashboard-Version"])
app.include_router(pipeline.router,     prefix="/api/pipeline",  tags=["Pipeline"])
app.include_router(orchestrator.router, prefix="/api",           tags=["Orchestrator"])
app.include_router(report_files.router, prefix="/api",           tags=["Reports"])
app.include_router(scan_pdf_endpoint.router, prefix="/api",      tags=["Scan PDF"])  # <-- NEW
