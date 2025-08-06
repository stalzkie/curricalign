from fastapi import APIRouter
from ...services.skill_extractor import extract_skills_from_jobs

router = APIRouter()

@router.post("/extract")
def extract_job_skills():
    result = extract_skills_from_jobs()
    return {"message": "Job skills extracted successfully", "result": result}
