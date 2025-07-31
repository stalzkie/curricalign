import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_job(job):
    data = {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "description": job.get("description"),
        "requirements": job.get("requirements"),
        "source": job.get("source"),
        "via": job.get("via"),
        "job_id": job.get("job_id"),
        "url": job.get("url")
    }

    try:
        return supabase.table("jobs").insert(data).execute()
    except Exception as e:
        print(f"❌ Supabase insert error: {e}")
        return {"status_code": 500, "error": str(e)}
    
def insert_multiple_jobs(jobs):
    """
    Inserts multiple job listings into the Supabase 'jobs' table.
    """
    for job in jobs:
        response = insert_job(job)
        if isinstance(response, dict) and response.get("status_code") == 500:
            print(f"⚠️ Failed to insert job: {job.get('title')} at {job.get('company')}")
        else:
            print(f"✅ Inserted job: {job.get('title')} at {job.get('company')}")
