import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

def insert_job(job):
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
        "matched_keyword": job.get("matched_keyword", ""),
        "posted_at": job.get("posted_at"),
        "scraped_at": job.get("scraped_at"),
    }

    try:
        return supabase.table("jobs").insert(data).execute()
    except Exception as e:
        print(f"❌ Supabase insert error: {e}")
        return {"status_code": 500, "error": str(e)}

def insert_multiple_jobs(jobs):
    for job in jobs:
        if "matched_keyword" not in job:
            job["matched_keyword"] = ""
        response = insert_job(job)
        if isinstance(response, dict) and response.get("status_code") == 500:
            print(f"⚠️ Failed to insert job: {job.get('title')} at {job.get('company')}")
        else:
            print(f"✅ Inserted job: {job.get('title')} at {job.get('company')}")

def load_cs_terms_from_supabase():
    try:
        res = supabase.table("cs_keywords").select("keyword").execute()
        return set(row["keyword"].lower() for row in res.data)
    except Exception as e:
        print(f"❌ Failed to fetch CS terms from Supabase: {e}")
        return set()
