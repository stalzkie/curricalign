from fastapi import APIRouter
from ...services.scraper import scrape_jobs_from_google_jobs
from ...core.supabase_client import insert_multiple_jobs

router = APIRouter()

@router.post("/scrape")
def scrape_and_store_jobs():
    jobs = scrape_jobs_from_google_jobs()
    insert_multiple_jobs(jobs)
    return {"message": f"Inserted {len(jobs)} job(s)."}
