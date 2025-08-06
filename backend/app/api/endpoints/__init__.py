from fastapi import APIRouter
from .evaluate import router as evaluate_router
from .jobs import router as jobs_router
from .pipeline import router as pipeline_router
from .queries import router as queries_router
from .report import router as report_router
from .skills import router as skills_router

router = APIRouter()

router.include_router(evaluate_router, prefix="/evaluate", tags=["Evaluate"])
router.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
router.include_router(pipeline_router, prefix="/pipeline", tags=["Pipeline"])
router.include_router(queries_router, prefix="/queries", tags=["Queries"])
router.include_router(report_router, prefix="/report", tags=["Report"])
router.include_router(skills_router, prefix="/skills", tags=["Skills"])
