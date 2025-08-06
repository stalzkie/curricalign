import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_job(job):
    # Ensure matched_keyword exists, even if blank
    data = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "description": job.get("description", ""),
        "requirements": job.get("requirements", ""),
        "source": job.get("source", ""),
        "via": job.get("via", ""),
        "job_id": job.get("job_id", ""),
        "url": job.get("url", ""),
        "matched_keyword": job.get("matched_keyword", ""),  # Ensured present
        "posted_at": job.get("posted_at"),       # ISO format expected
        "scraped_at": job.get("scraped_at"),     # ISO format expected
    }

    try:
        return supabase.table("jobs").insert(data).execute()
    except Exception as e:
        print(f"❌ Supabase insert error: {e}")
        return {"status_code": 500, "error": str(e)}

def insert_multiple_jobs(jobs):
    for job in jobs:
        # Ensure matched_keyword key exists before insertion
        if "matched_keyword" not in job:
            job["matched_keyword"] = ""
        response = insert_job(job)
        if isinstance(response, dict) and response.get("status_code") == 500:
            print(f"⚠️ Failed to insert job: {job.get('title')} at {job.get('company')}")
        else:
            print(f"✅ Inserted job: {job.get('title')} at {job.get('company')}")
