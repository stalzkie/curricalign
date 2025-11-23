from datetime import datetime
from dotenv import load_dotenv
from serpapi.google_search import GoogleSearch
from data.course_descriptions import COURSE_DESCRIPTIONS  # (not used here yet, probably for future matching)

from .query_generator import get_top_keywords  # gets trending/important keywords to search jobs with
from .query_logger import log_query            # saves some metadata about each search
from ..core.supabase_client import insert_multiple_jobs  # bulk insert jobs to Supabase
from .update_cs_keywords import update_cs_keywords       # refresh CS keywords list in DB
from .trending_jobs import compute_trending_jobs         # compute trending job titles after scraping

from supabase import create_client, Client
import os

# load environment variables from .env (keys, URLs, etc.)
load_dotenv()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# connect to Supabase (so we can store jobs / read keywords)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# we only keep results that seem to come from these sources
TARGET_SOURCES = ["jobstreet", "indeed", "linkedin", "glassdoor"]

def load_cs_terms_from_supabase():
    try:
        res = supabase.table("cs_keywords").select("keyword").execute()
        return set(row["keyword"].lower() for row in res.data)
    except Exception as e:
        print(f"❌ Failed to fetch CS terms from Supabase: {e}")
        return set()

def scrape_jobs_from_google_jobs(location: str = "Philippines", top_n_keywords: int = 10, jobs_per_query: int = 5):

    cs_terms = load_cs_terms_from_supabase()
    keyword_list = get_top_keywords(n=top_n_keywords)

    print("📈 Top keywords from Google Trends:", keyword_list)
    all_jobs = []

    for keyword in keyword_list:
        print(f"🔍 Searching for: {keyword}")

        sources = ["JobStreet", "Indeed", "LinkedIn", "Glassdoor"]

        variations = [f"{source} {keyword} developer jobs in {location}" for source in sources] + [
            f"{keyword} developer site:jobstreet.com.ph",
            f"{keyword} developer site:ph.indeed.com",
            f"{keyword} developer site:linkedin.com/jobs",
            f"{keyword} developer site:glassdoor.com",
            f"{keyword} IT jobs in {location}",
            f"{keyword} software engineer Philippines",
            f"{keyword} backend developer Philippines",
            f"{keyword} frontend developer Philippines"
        ]

        collected = []
        seen_job_ids = set()
        variation_attempts = 0
        max_attempts = 10

        while len(collected) < jobs_per_query and variation_attempts < max_attempts:

            # GLOBAL HARD LIMIT: stop scraping if we already have n jobs
            if len(all_jobs) >= 10:
                break

            variation = variations[variation_attempts % len(variations)]
            variation_attempts += 1

            params = {
                "engine": "google_jobs",
                "q": variation,
                "hl": "en",
                "gl": "ph",
                "api_key": SERPAPI_API_KEY
            }

            try:
                search = GoogleSearch(params)
                results = search.get_dict()
                jobs = results.get("jobs_results", [])

                for job in jobs:
                    if len(all_jobs) >= 10: #another hard limiter for scraped jobs applied to preserve tokens
                        break 

                    job_id = job.get("job_id", "N/A")
                    if job_id in seen_job_ids:
                        continue

                    via = job.get("via", "").lower()
                    if not any(source in via for source in TARGET_SOURCES):
                        continue

                    extensions = job.get("detected_extensions", {})
                    posted_text = extensions.get("posted_at", "").lower()
                    posted_at = None
                    if any(x in posted_text for x in ["hour", "day", "today", "just posted"]):
                        posted_at = datetime.utcnow().isoformat()

                    job_data = {
                        "source": "Google Jobs via SerpApi",
                        "title": job.get("title", "N/A"),
                        "company": job.get("company_name", "N/A"),
                        "location": job.get("location", location),
                        "via": job.get("via", "N/A"),
                        "description": job.get("description", "N/A"),
                        "requirements": extract_requirements(job.get("job_highlights", [])),
                        "job_id": job_id,
                        "url": job.get("related_links", [{}])[0].get("link", "N/A"),
                        "matched_keyword": keyword,
                        "posted_at": posted_at,
                        "scraped_at": datetime.utcnow().isoformat()
                    }

                    collected.append(job_data)
                    seen_job_ids.add(job_id)

                    all_jobs.append(job_data)  # append directly to global list

                    if len(all_jobs) >= 10:
                        break  # 🔥 EARLY STOP

                log_query(
                    query=variation,
                    is_cs_term=int(any(term in variation.lower() for term in cs_terms)),
                    word_count=len(variation.split()),
                    trend_value=0,
                    jobs_returned=len(jobs),
                    matched_skills_count=estimate_matched_skills(jobs, cs_terms),
                    avg_subject_score=None
                )

            except Exception as e:
                print(f"❌ Error fetching jobs for '{variation}': {e}")
                continue

        if len(all_jobs) >= 10:
            break  # 🔥 GLOBAL STOP AFTER ALL VARIATIONS

    # 🔥 HARD LIMIT: only keep first 10 jobs
    all_jobs = all_jobs[:10]

    if all_jobs:
        print(f"💾 Saving {len(all_jobs)} jobs to Supabase...")
        insert_multiple_jobs(all_jobs)

    return all_jobs

def extract_requirements(highlights):
    for section in highlights:
        title = section.get("title", "")
        if "Qualifications" in title or "Requirements" in title:
            return " ".join(section.get("items", []))
    return "Not specified"

def estimate_matched_skills(jobs, cs_terms):
    skills = set()
    for job in jobs:
        text = (job.get("description", "") + " " + job.get("requirements", "")).lower()
        for term in cs_terms:
            if term in text:
                skills.add(term)
    return len(skills)

if __name__ == "__main__":
    scrape_jobs_from_google_jobs()
    update_cs_keywords()
    compute_trending_jobs()
