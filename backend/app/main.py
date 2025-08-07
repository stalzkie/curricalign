from fastapi import FastAPI
from .api.endpoints import router as api_router
from app.api.endpoints import dashboard, pipeline

app = FastAPI(
    title="CurricAlign API",
    description="API for curriculum-job market alignment pipeline.",
    version="1.0.0",
)

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to the CurricAlign API"}

# Mount all API routes under /api
app.include_router(api_router, prefix="/api")
app.include_router(dashboard.router)
app.include_router(pipeline.router)