# backend/app/main.py

# --- NEW IMPORTS for Lifespan and Supabase ---
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client

# --- Your existing router imports ---
from .api.endpoints import dashboard, pipeline, orchestrator, report_files
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
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:3000"],  # add your prod origin if any
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- STATIC MOUNTS ----
_static_root = os.path.join(os.path.dirname(__file__), "..", "static")
_reports_dir = os.path.join(_static_root, "reports")
os.makedirs(_reports_dir, exist_ok=True)

# Serves /static/*
app.mount("/static", StaticFiles(directory=_static_root), name="static")

# 👉 Serves /api/reports/* (PDFs must be written to _reports_dir)
app.mount("/api/reports", StaticFiles(directory=_reports_dir), name="reports")

@app.get("/")
def read_root():
    return {"message": "Welcome to the CurricAlign API"}

# Routers
app.include_router(dashboard.router,   prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(pipeline.router,    prefix="/api/pipeline",  tags=["Pipeline"])
app.include_router(orchestrator.router, prefix="/api",          tags=["Orchestrator"])
app.include_router(report_files.router, prefix="/api",          tags=["Reports"])
