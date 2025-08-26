import os
import time
from supabase import create_client, Client
from dotenv import load_dotenv
import httpx
from httpx import RemoteProtocolError

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE_URL and SUPABASE_KEY must be set.")

# Create Supabase client 
def create_supabase_client() -> Client:
    """Always create a fresh Supabase client (v1.x compatible)."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Global client
supabase: Client = create_supabase_client()

def get_supabase_client() -> Client:
    """Create a *new* client each time."""
    return create_supabase_client()

# Retry wrapper
def supabase_query_with_retry(query_func, max_attempts=3, delay=0.2):
    last_exception = None
    for attempt in range(1, max_attempts + 1):
        try:
            return query_func()
        except RemoteProtocolError as e:
            print(f"⚠️ Attempt {attempt} failed with RemoteProtocolError: {e}")
            last_exception = e
            time.sleep(delay)
        except httpx.HTTPError as e:
            print(f"⚠️ Attempt {attempt} failed with HTTPError: {e}")
            last_exception = e
            time.sleep(delay)
    raise last_exception

# Helper DB functions-
def insert_job(job: dict):
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
        return supabase_query_with_retry(
            lambda: supabase.table("jobs").insert(data).execute()
        )
    except Exception as e:
        print(f"❌ Supabase insert error: {e}")
        return {"status_code": 500, "error": str(e)}

def insert_multiple_jobs(jobs: list):
    for job in jobs:
        if "matched_keyword" not in job:
            job["matched_keyword"] = ""
        response = insert_job(job)
        if isinstance(response, dict) and response.get("status_code") == 500:
            print(f"⚠️ Failed: {job.get('title')} at {job.get('company')}")
        else:
            print(f"✅ Inserted: {job.get('title')} at {job.get('company')}")

def load_cs_terms_from_supabase() -> set:
    try:
        res = supabase_query_with_retry(
            lambda: supabase.table("cs_keywords").select("keyword").execute()
        )
        return set(row["keyword"].lower() for row in res.data)
    except Exception as e:
        print(f"❌ Failed to fetch CS terms: {e}")
        return set()
