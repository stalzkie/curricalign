# backend/app/main.py

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client

# Routers
from .api.endpoints import dashboard, pipeline, orchestrator, report_files

# Some environments have quirky HTTP/2 behavior; disable if needed.
os.environ.setdefault("HTTPX_DISABLE_HTTP2", "1")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO:     Application startup...")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment.")
    supabase_client: Client = create_client(supabase_url, supabase_key)
    app.state.supabase = supabase_client
    print("INFO:     Supabase client created and attached to app state.")
    yield
    print("INFO:     Application shutdown.")

app = FastAPI(
    title="CurricAlign API",
    description="API for curriculum-job market alignment pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- STATIC MOUNTS ----------
# This file is backend/app/main.py -> parent is backend/app
APP_DIR = Path(__file__).resolve().parent                  # backend/app
STATIC_DIR = (APP_DIR / "static").resolve()                # backend/app/static  ✅ correct
REPORTS_DIR = (STATIC_DIR / "reports").resolve()           # backend/app/static/reports
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Serves /static/* (including /static/reports/<file>.pdf)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ⚠️ DO NOT also mount /api/reports via StaticFiles if you keep the router below
# app.mount("/api/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")

@app.get("/")
def read_root():
    return {"message": "Welcome to the CurricAlign API"}

# ---------- ROUTERS ----------
app.include_router(dashboard.router,    prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(pipeline.router,     prefix="/api/pipeline",  tags=["Pipeline"])
app.include_router(orchestrator.router, prefix="/api",           tags=["Orchestrator"])
# Keep the validated reports router at /api/reports/{filename}
app.include_router(report_files.router, prefix="/api",           tags=["Reports"])
