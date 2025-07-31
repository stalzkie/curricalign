import os
from dotenv import load_dotenv
from serpapi.google_search import GoogleSearch
from course_descriptions import COURSE_DESCRIPTIONS
from query_generator import get_top_keywords, CS_TERMS
from query_logger import log_query
from supabase_client import insert_multiple_jobs  # ✅ Supabase integration

load_dotenv()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
TARGET_SOURCES = ["jobstreet", "indeed", "linkedin", "glassdoor"]


def scrape_jobs_from_google_jobs(
    location: str = "Philippines",
    top_n_keywords: int = 10,
    jobs_per_query: int = 3
):
    syllabus_text = "\n".join(COURSE_DESCRIPTIONS.values())
    keyword_list = get_top_keywords(syllabus_text, n=top_n_keywords)

    print("📈 Top keywords from Google Trends:", keyword_list)

    all_jobs = []

    for keyword in keyword_list:
        print(f"🔍 Searching for: {keyword}")

        sources = ["JobStreet", "Indeed", "LinkedIn", "Glassdoor"]

        variations = [
            f"{source} {keyword} developer jobs in {location}" for source in sources
        ] + [
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
        max_attempts = 12

        while len(collected) < jobs_per_query and variation_attempts < max_attempts:
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
                    job_id = job.get("job_id", "N/A")
                    if job_id in seen_job_ids:
                        continue

                    via = job.get("via", "").lower()
                    if not any(source in via for source in TARGET_SOURCES):
                        continue  # ✅ Only allow specified job boards

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
                        "matched_keyword": keyword
                    }

                    collected.append(job_data)
                    seen_job_ids.add(job_id)

                    if len(collected) >= jobs_per_query:
                        break

                log_query(
                    query=variation,
                    is_cs_term=int(any(term in variation.lower() for term in CS_TERMS)),
                    word_count=len(variation.split()),
                    trend_value=0,
                    jobs_returned=len(jobs),
                    matched_skills_count=estimate_matched_skills(jobs),
                    avg_subject_score=None
                )

            except Exception as e:
                print(f"❌ Error fetching jobs for '{variation}': {e}")
                continue

        if not collected:
            print(f"⚠️ No jobs found for: {keyword}")
        else:
            all_jobs.extend(collected)

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


def estimate_matched_skills(jobs):
    skills = set()
    for job in jobs:
        text = (job.get("description", "") + " " + job.get("requirements", "")).lower()
        for term in CS_TERMS:
            if term in text:
                skills.add(term)
    return len(skills)
