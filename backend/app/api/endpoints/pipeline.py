from fastapi import APIRouter
from ...services.scraper import scrape_jobs_from_google_jobs
from ...services.skill_extractor import extract_skills_from_jobs
from ...core.supabase_client import insert_multiple_jobs

router = APIRouter()


@router.post("/pipeline/scrape-jobs")
def scrape_and_store_jobs():
    jobs = scrape_jobs_from_google_jobs()
    insert_multiple_jobs(jobs)
    return {"message": f"Inserted {len(jobs)} job(s)."}


@router.post("/pipeline/extract-skills")
def extract_job_skills():
    result = extract_skills_from_jobs()
    return {"message": "Job skills extracted successfully", "result": result}
