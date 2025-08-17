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
    """
    Grab the latest CS keywords from Supabase so we can:
    1) mark which queries are CS-related
    2) estimate matched skills in job text
    """
    try:
        res = supabase.table("cs_keywords").select("keyword").execute()
        # return a set of lowercase keywords for quick lookup
        return set(row["keyword"].lower() for row in res.data)
    except Exception as e:
        print(f"❌ Failed to fetch CS terms from Supabase: {e}")
        return set()

def scrape_jobs_from_google_jobs(location: str = "Philippines", top_n_keywords: int = 20, jobs_per_query: int = 10):
    """
    Main function:
    - gets top keywords (e.g., from Google Trends)
    - builds a bunch of query variations per keyword
    - calls SerpApi (Google Jobs) to get jobs
    - filters by source (JobStreet/Indeed/LinkedIn/Glassdoor)
    - saves to Supabase in bulk
    """
    cs_terms = load_cs_terms_from_supabase()  # always get fresh terms when we start
    keyword_list = get_top_keywords(n=top_n_keywords)

    print("📈 Top keywords from Google Trends:", keyword_list)
    all_jobs = []  # we will store all collected jobs here and save once at the end

    for keyword in keyword_list:
        print(f"🔍 Searching for: {keyword}")

        # These are the sites we care about (to avoid random boards)
        sources = ["JobStreet", "Indeed", "LinkedIn", "Glassdoor"]

        # Make multiple variations so the search is broader
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

        collected = []        # jobs we found for this keyword
        seen_job_ids = set()  # to avoid duplicates across variations
        variation_attempts = 0
        max_attempts = 12     # don't loop forever

        # keep trying different variations until we get enough jobs or hit the cap
        while len(collected) < jobs_per_query and variation_attempts < max_attempts:
            variation = variations[variation_attempts % len(variations)]
            variation_attempts += 1

            # SerpApi params for Google Jobs
            params = {
                "engine": "google_jobs",
                "q": variation,
                "hl": "en",
                "gl": "ph",
                "api_key": SERPAPI_API_KEY
            }

            try:
                # make the request and parse results
                search = GoogleSearch(params)
                results = search.get_dict()
                jobs = results.get("jobs_results", [])

                for job in jobs:
                    job_id = job.get("job_id", "N/A")
                    if job_id in seen_job_ids:
                        continue  # skip duplicate result

                    # only keep jobs that look like they came from our target sources
                    via = job.get("via", "").lower()
                    if not any(source in via for source in TARGET_SOURCES):
                        continue

                    # try to detect if the job was posted very recently
                    extensions = job.get("detected_extensions", {})
                    posted_text = extensions.get("posted_at", "").lower()
                    posted_at = None
                    if any(x in posted_text for x in ["hour", "day", "today", "just posted"]):
                        posted_at = datetime.utcnow().isoformat()

                    # transform SerpApi job fields into our own structure
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
                        "matched_keyword": keyword,  # which keyword led us to this job
                        "posted_at": posted_at,      # only filled if we think it's very recent
                        "scraped_at": datetime.utcnow().isoformat()
                    }

                    collected.append(job_data)
                    seen_job_ids.add(job_id)

                    if len(collected) >= jobs_per_query:
                        break  # stop early if we already got enough jobs for this keyword

                # log the query we just ran (for analysis/monitoring)
                log_query(
                    query=variation,
                    is_cs_term=int(any(term in variation.lower() for term in cs_terms)),
                    word_count=len(variation.split()),
                    trend_value=0,  # if you have a trend score, put it here
                    jobs_returned=len(jobs),
                    matched_skills_count=estimate_matched_skills(jobs, cs_terms),
                    avg_subject_score=None  # not available here
                )

            except Exception as e:
                # network errors, rate limits, etc.
                print(f"❌ Error fetching jobs for '{variation}': {e}")
                continue

        # after trying multiple variations for this keyword, collect what we found
        if collected:
            all_jobs.extend(collected)
        else:
            print(f"⚠️ No jobs found for: {keyword}")

    # save everything in one go (fewer DB round trips)
    if all_jobs:
        print(f"💾 Saving {len(all_jobs)} jobs to Supabase...")
        insert_multiple_jobs(all_jobs)

    return all_jobs

def extract_requirements(highlights):
    """
    SerpApi sometimes provides 'job_highlights' with sections like:
    - 'Qualifications'
    - 'Requirements'
    We just grab the items from those sections and join them as one string.
    """
    for section in highlights:
        title = section.get("title", "")
        if "Qualifications" in title or "Requirements" in title:
            return " ".join(section.get("items", []))
    return "Not specified"

def estimate_matched_skills(jobs, cs_terms):
    """
    Quick & simple: count how many CS terms appear at least once across all job descriptions.
    This gives us a rough idea of skill presence per query.
    """
    skills = set()
    for job in jobs:
        text = (job.get("description", "") + " " + job.get("requirements", "")).lower()
        for term in cs_terms:
            if term in text:
                skills.add(term)
    return len(skills)

if __name__ == "__main__":
    # running this file directly will:
    # 1) scrape jobs
    # 2) refresh CS keywords
    # 3) recompute trending jobs
    scrape_jobs_from_google_jobs()
    update_cs_keywords()
    compute_trending_jobs()
