# apps/backend/main.py

import os
from contextlib import asynccontextmanager
from pathlib import Path
import logging
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from supabase import create_client, Client

# 🔑 MODERN SDK IMPORTS
from google import genai
from google.genai import types 

# Routers
from .api.endpoints import dashboard, pipeline, orchestrator, report_files, version
from .api.endpoints import scan_pdf as scan_pdf_endpoint  # <-- PDF scan/upload

# -------------------------------------------------------------------
# Environment / logging
# -------------------------------------------------------------------
os.environ.setdefault("HTTPX_DISABLE_HTTP2", "1")  # Cloudflare/HTTP2 quirks
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [main] %(message)s",
)

# Central Gemini config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro-latest").strip()

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

    # --- Supabase client attach ---
    url, key = _get_service_key()
    sb: Client = create_client(url, key)
    app.state.supabase = sb
    logging.info("Supabase service client attached to app.state.supabase")

    # Quick probe: tiny exact count to confirm RLS/keys are correct.
    try:
        resp = (
            sb.from_("course_alignment_scores_clean")
            .select("course_alignment_score_clean_id", count="exact")
            .range(0, 0)
            .execute()
        )
        cnt = int(getattr(resp, "count", 0) or 0)
        logging.info("[probe] course_alignment_scores_clean count=%s", cnt)
    except Exception as e:
        logging.warning("[probe] count failed: %r", e)

    # --- Gemini v1 client initialization and probe ---
    app.state.gemini_client = None
    if not GEMINI_API_KEY:
        logging.error("[Gemini] GEMINI_API_KEY is missing; Gemini features will fail.")
    else:
        try:
            # 🎯 REVISED: Initialize the modern client and attach it to app.state
            gemini_client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=types.HttpOptions(api_version='v1')
            )
            app.state.gemini_client = gemini_client

            # Listing models now uses the client object
            models = [m.name for m in gemini_client.list_models()[:8]]
            logging.info("[Gemini] OK. Model env=%s  sample=%s", GEMINI_MODEL, models)
        except Exception as e:
            logging.exception(
                "[Gemini] FAILED to initialize or list models. Details: %r", e
            )

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
# You can pass one or multiple frontend origins via FRONTEND_ORIGIN
# e.g. FRONTEND_ORIGIN="http://localhost:3000,https://your-frontend.vercel.app"
raw_frontends = os.getenv("FRONTEND_ORIGIN", "").strip()
allowed_origins: List[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost",
]
if raw_frontends:
    for origin in raw_frontends.split(","):
        origin = origin.strip()
        if origin:
            allowed_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,                         # explicit origins
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
# IMPORTANT:
# main.py lives at: apps/backend/main.py
# Your static dir is under: apps/backend/app/static
# So APP_DIR must be apps/backend/app (NOT apps/backend)
ROOT_DIR = Path(__file__).resolve().parent            # apps/backend
APP_DIR = (ROOT_DIR / "app").resolve()                # apps/backend/app
STATIC_DIR = (APP_DIR / "static").resolve()           # apps/backend/app/static
REPORTS_DIR = (STATIC_DIR / "reports").resolve()      # apps/backend/app/static/reports
STATIC_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Expose to other modules via app.state (optional, handy for debugging)
app.state.APP_DIR = APP_DIR
app.state.STATIC_DIR = STATIC_DIR
app.state.REPORTS_DIR = REPORTS_DIR

# Log computed paths so Railway logs show the truth
logging.info("[paths] ROOT_DIR=%s", ROOT_DIR)
logging.info("[paths] APP_DIR=%s", APP_DIR)
logging.info("[paths] STATIC_DIR=%s", STATIC_DIR)
logging.info("[paths] REPORTS_DIR=%s", REPORTS_DIR)

# Mount static serving at /static
# Starlette's StaticFiles supports GET and HEAD.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Public URL pieces used by services/orchestrator when building the report URL
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://curricalign-production.up.railway.app").rstrip("/")
STATIC_URL_PREFIX = os.getenv("STATIC_URL_PREFIX", "/static").rstrip("/")
logging.info("[public] PUBLIC_BASE_URL=%s", PUBLIC_BASE_URL)
logging.info("[public] STATIC_URL_PREFIX=%s", STATIC_URL_PREFIX)

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
# Debug (helps confirm PDFs are where we expect in Railway)
# -------------------------------------------------------------------
@app.get("/api/debug/info")
def debug_info():
    return {
        "public_base_url": PUBLIC_BASE_URL,
        "static_url_prefix": STATIC_URL_PREFIX,
        "root_dir": str(ROOT_DIR),
        "app_dir": str(APP_DIR),
        "static_dir": str(STATIC_DIR),
        "reports_dir": str(REPORTS_DIR),
    }

@app.get("/api/debug/reports")
def list_reports():
    try:
        files = sorted([p.name for p in REPORTS_DIR.glob("*.pdf")])
        return {"count": len(files), "files": files}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------------------------------------------------
# Gemini runtime health (on-demand)
# -------------------------------------------------------------------
@app.get("/api/health/gemini")
def gemini_health():
    """
    Lists a few models to confirm the API key + v1 endpoint are working.
    """
    client: genai.Client | None = getattr(app.state, "gemini_client", None)
    
    if not client:
        return JSONResponse(status_code=500, content={"error": "Gemini client not initialized. Check GEMINI_API_KEY."})

    try:
        # 🎯 REVISED: Use the client object attached to app.state
        names = [m.name for m in client.list_models()[:10]]
        return {"ok": True, "model_env": GEMINI_MODEL, "sample_models": names}
    except Exception as e:
        logging.exception("[Gemini] health check failed")
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------
app.include_router(dashboard.router,          prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(version.router,            prefix="/api/dashboard", tags=["Dashboard-Version"])
app.include_router(pipeline.router,           prefix="/api/pipeline",  tags=["Pipeline"])
app.include_router(orchestrator.router,       prefix="/api",           tags=["Orchestrator"])
app.include_router(report_files.router,       prefix="/api",           tags=["Reports"])
app.include_router(scan_pdf_endpoint.router,  prefix="/api",           tags=["Scan PDF"])