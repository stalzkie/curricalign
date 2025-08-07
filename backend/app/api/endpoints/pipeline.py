from fastapi import APIRouter
from ...services.orchestrator import run_pipeline

router = APIRouter()

@router.post("/run")
def run_full_pipeline():
    result = run_pipeline()
    return {"message": "Pipeline executed", "result": result}
